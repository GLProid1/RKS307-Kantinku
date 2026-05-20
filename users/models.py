from django.db import models
from django.contrib.auth.models import User
import pyotp

class UserMFA(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='usermfa')
    secret_key = models.CharField(max_length=255, blank=True, null=True)
    is_enabled = models.BooleanField(default=False)

    def generate_secret(self):
        # Generate base32 secret key untuk TOTP
        self.secret_key = pyotp.random_base32()
        self.save()
        return self.secret_key

class BackupCode(models.Model):
    mfa = models.ForeignKey(UserMFA, on_delete=models.CASCADE, related_name='backup_codes')
    code_hash = models.CharField(max_length=255) # Disimpan dalam bentuk hash demi keamanan
    is_used = models.BooleanField(default=False)