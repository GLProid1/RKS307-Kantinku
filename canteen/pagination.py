from rest_framework.pagination import PageNumberPagination

class DefaultPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    
    # INI YANG PALING PENTING - Hard limit untuk mencegah server kehabisan RAM
    # Walaupun user mengirim /api/orders/?page_size=999999,
    # server hanya akan membalas maksimal 50 baris data.
    max_page_size = 50