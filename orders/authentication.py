from rest_framework.authentication import SessionAuthentication

class CsrfExemptSessionAuthentication(SessionAuthentication):
    """
    Menonaktifkan validasi CSRF untuk Session Authentication.
    Gunakan ini untuk development atau API internal.
    """
    def enforce_csrf(self, request):
        return  # Untuk tidak melakukan pemeriksaan csrf