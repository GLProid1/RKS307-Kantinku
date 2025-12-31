from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import timedelta
from orders.models import Order

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def report_summary(request):
    # --- 1. SETUP DATA UMUM ---
    periode = request.query_params.get('periode', 'hari-ini')
    stand_id = request.query_params.get('stand_id')
    today = timezone.now().date()

    # Base Queryset: Ambil SEMUA order (jangan filter status dulu)
    # Filter waktu dasar
    base_queryset = Order.objects.all()
    
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
    # Frontend meminta: stats_today (total_revenue_cash, completed, pending)
    
    # Hitung agregat untuk dashboard
    dashboard_stats = base_queryset.aggregate(
        # Revenue: Hanya yang CASH dan Statusnya SELESAI/PAID
        rev_cash=Sum('total', filter=Q(payment_method='CASH', status__in=['COMPLETED', 'PAID', 'READY'])),
        
        # Completed: Semua pesanan yang tidak dibatalkan/pending
        count_completed=Count('id', filter=Q(status__in=['COMPLETED', 'PAID', 'READY', 'PROCESSING'])),
        
        # Pending: Khusus yang AWAITING_PAYMENT
        count_pending=Count('id', filter=Q(status='AWAITING_PAYMENT'))
    )

    stats_today = {
        'total_revenue_cash': dashboard_stats['rev_cash'] or 0,
        'completed': dashboard_stats['count_completed'] or 0,
        'pending': dashboard_stats['count_pending'] or 0,
    }

    # Hitung Stand Performance (Top Stands)
    # Mengelompokkan berdasarkan nama tenant dan menjumlahkan total penjualan (yang sukses saja)
    stand_perf_qs = base_queryset.filter(status__in=['COMPLETED', 'PAID', 'READY']).values('tenant__name').annotate(
        value=Sum('total')
    ).order_by('-value')[:5] # Ambil top 5

    stand_performance = [
        {'name': item['tenant__name'], 'value': item['value'] or 0} 
        for item in stand_perf_qs
    ]

    # --- 3. LOGIKA UNTUK HALAMAN LAPORAN KEUANGAN (LaporanKeuanganPage.jsx) ---
    # Logika lama tetap dipertahankan agar halaman laporan tidak error
    
    # Filter khusus transaksi sukses untuk tabel laporan
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

    # List transaksi untuk tabel
    transactions_data = report_queryset.order_by('-created_at')[:50]
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

    # --- 4. RETURN GABUNGAN ---
    return Response({
        # Data untuk LaporanKeuanganPage
        'stats': stats_report,
        'transactions': transactions_list,
        
        # Data untuk DashboardPage (BARU)
        'stats_today': stats_today,
        'stand_performance': stand_performance
    })
