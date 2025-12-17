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
    # 1. Ambil Parameter Filter
    periode = request.query_params.get('periode', 'hari-ini')
    stand_id = request.query_params.get('stand_id')

    # 2. Query Awal: Hanya Order yang SUDAH DIBAYAR/SELESAI
    # Sesuaikan status ini dengan sistem kamu. Biasanya 'PAID' atau 'COMPLETED'
    valid_statuses = ['PAID', 'PROCESSING', 'READY', 'COMPLETED']
    queryset = Order.objects.filter(status__in=valid_statuses)

    # 3. Filter Stand (Jika ada)
    if stand_id and stand_id != 'semua':
        queryset = queryset.filter(tenant_id=stand_id)

    # 4. Filter Waktu
    today = timezone.now().date()
    if periode == 'hari-ini':
        queryset = queryset.filter(created_at__date=today)
    elif periode == 'kemarin':
        yesterday = today - timedelta(days=1)
        queryset = queryset.filter(created_at__date=yesterday)
    elif periode == '7-hari':
        week_ago = today - timedelta(days=7)
        queryset = queryset.filter(created_at__date__gte=week_ago)

    # 5. HITUNG STATISTIK (Ini yang dicari Frontend)
    agg_data = queryset.aggregate(
        total_tunai=Sum('total', filter=Q(payment_method='CASH')),
        total_transfer=Sum('total', filter=Q(payment_method='TRANSFER')),
        total_trx=Count('id')
    )

    # Pastikan data ini dikirim dengan kunci 'stats'
    stats = {
        'totalPendapatanTunai': agg_data['total_tunai'] or 0,
        'totalPendapatanTransfer': agg_data['total_transfer'] or 0,
        'totalTransaksi': agg_data['total_trx'] or 0,
    }

    # 6. Data Transaksi untuk Tabel
    transactions_data = queryset.order_by('-created_at')[:50]
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

    # KIRIM RESPON JSON
    return Response({
        'stats': stats,
        'transactions': transactions_list
    })