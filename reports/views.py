from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import timedelta
from orders.models import Order
from django.core.cache import cache

CACHE_VERSION = "v1"

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def report_summary(request):
    # --- 1. SETUP DATA UMUM ---
    periode = request.query_params.get('periode', 'hari-ini')
    stand_id = request.query_params.get('stand_id', 'semua')
    
    cache_key = f"{CACHE_VERSION}_dashboard_report_{periode}_{stand_id}"
    cache_timeout = 60 if periode == 'hari-ini' else 300
    
    cached_data = cache.get(cache_key)
    
    # Jika data ada di cache, langsung return tanpa hit database
    if cached_data:
        return Response(cached_data)
        
    lock_key = f"lock_{cache_key}"
    
    # Memastikan hanya 1 request yang mengeksekusi query database jika cache kosong (Stampede Protection)
    if cache.add(lock_key, "1", timeout=10):
        try:
            today = timezone.now().date()

            # Base Queryset: Ambil SEMUA order (jangan filter status dulu)
            base_queryset = Order.objects.all()
            
            # Filter waktu dasar
            if periode == 'hari-ini':
                base_queryset = base_queryset.filter(created_at__date=today)
            elif periode == 'kemarin':
                yesterday = today - timedelta(days=1)
                base_queryset = base_queryset.filter(created_at__date=yesterday)
            elif periode == '7-hari':
                week_ago = today - timedelta(days=7)
                base_queryset = base_queryset.filter(created_at__date__gte=week_ago)

            # Filter Stand (Jika user memilih stand tertentu)
            if stand_id and stand_id != 'semua':
                base_queryset = base_queryset.filter(tenant_id=stand_id)

            # --- 2. LOGIKA UNTUK HALAMAN DASHBOARD (DashboardPage.jsx) ---
            # Hitung agregat untuk dashboard
            dashboard_stats = base_queryset.aggregate(
                rev_cash=Sum('total', filter=Q(payment_method='CASH', status__in=['COMPLETED', 'PAID', 'READY'])),
                count_completed=Count('id', filter=Q(status__in=['COMPLETED', 'PAID', 'READY', 'PROCESSING'])),
                count_pending=Count('id', filter=Q(status='AWAITING_PAYMENT'))
            )

            stats_today = {
                'total_revenue_cash': dashboard_stats['rev_cash'] or 0,
                'completed': dashboard_stats['count_completed'] or 0,
                'pending': dashboard_stats['count_pending'] or 0,
            }

            # Hitung Stand Performance (Top Stands)
            stand_perf_qs = base_queryset.filter(status__in=['COMPLETED', 'PAID', 'READY']).values('tenant__name').annotate(
                value=Sum('total')
            ).order_by('-value')[:5]

            stand_performance = [
                {'name': item['tenant__name'], 'value': item['value'] or 0} 
                for item in stand_perf_qs
            ]

            # --- 3. LOGIKA UNTUK HALAMAN LAPORAN KEUANGAN ---
            valid_statuses = ['PAID', 'PROCESSING', 'READY', 'COMPLETED']
            report_queryset = base_queryset.filter(status__in=valid_statuses)

            agg_report = report_queryset.aggregate(
                total_tunai=Sum('total', filter=Q(payment_method='CASH')),
                total_transfer=Sum('total', filter=Q(payment_method='TRANSFER')),
                total_trx=Count('id')
            )

            stats_report = {
                'totalPendapatanTunai': agg_report['total_tunai'] or 0,
                'totalPendapatanTransfer': agg_report['total_transfer'] or 0,
                'totalTransaksi': agg_report['total_trx'] or 0,
            }

            # [POINT 10]: select_related() SEBELUM cache untuk menghindari N+1 
            transactions_data = report_queryset.select_related('customer', 'tenant').order_by('-created_at')[:50]
            transactions_list = []
            for trx in transactions_data:
                transactions_list.append({
                    'id': trx.id,
                    'references_code': trx.references_code,
                    'customer_name': trx.customer.name if trx.customer else 'Guest',
                    'total': trx.total,
                    'status': trx.status,
                    'payment_method': trx.payment_method,
                    'created_at': trx.created_at,
                    'tenant_name': trx.tenant.name
                })

            response_data = {
                'stats': stats_report,
                'transactions': transactions_list,
                'stats_today': stats_today,
                'stand_performance': stand_performance
            }
            
            # Simpan ke cache
            cache.set(cache_key, response_data, timeout=cache_timeout)
            
        finally:
            cache.delete(lock_key) # Lepas lock setelah selesai
            
        return Response(response_data)
        
    else:
        # Jika sedang di-lock oleh thread lain, beri instruksi client untuk coba lagi
        return Response({"detail": "Memproses laporan, silakan refresh."}, status=503)