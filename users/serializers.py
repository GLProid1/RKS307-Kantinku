from rest_framework import serializers
from django.contrib.auth.models import User, Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.apps import apps
from django.db import transaction
# from tenants.models import Tenant
import string
import random

class UserSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    # Kita tambahkan inisialisasi field-nya agar terbaca
    is_mfa_enabled = serializers.SerializerMethodField()

    class Meta:
        model = User
        # TAMBAHKAN 'is_mfa_enabled' KE DALAM LIST INI
        fields = ['id', 'username', 'email', 'role', 'first_name', 'last_name', 'is_mfa_enabled']

    def get_role(self, obj):
        # 1. Jika dia adalah superuser, otomatis anggap sebagai 'admin'
        if obj.is_superuser:
            return 'admin'
            
        # 2. Jika bukan superuser, cek grupnya (untuk Seller / Cashier)
        group = obj.groups.first()
        if group:
            return group.name.lower()
            
        # 3. Default jika tidak punya grup
        return 'customer'

    def get_is_mfa_enabled(self, obj):
        if hasattr(obj, 'usermfa'):
            return obj.usermfa.is_enabled
        return False

class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    role = serializers.CharField(write_only=True)
    stand_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    
    # TAMBAHAN: Tangkap ID Stand jika Admin memilih "Gabung Stand Lama"
    existing_tenant_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'role', 'stand_name', 'existing_tenant_id']

    def validate_role(self, value):
        valid_roles = ['admin', 'seller', 'cashier']
        if value.lower() not in valid_roles:
            raise serializers.ValidationError(f"'{value}' bukan pilihan role yang valid.")
        return value.capitalize()

    def create(self, validated_data):
        with transaction.atomic():
            role_name = validated_data.pop('role')
            stand_name = validated_data.pop('stand_name', None)
            existing_tenant_id = validated_data.pop('existing_tenant_id', None)
            
            user = User.objects.create_user(**validated_data)
            group, _ = Group.objects.get_or_create(name=role_name)
            user.groups.add(group)
            
            if role_name == 'Admin':
                user.is_staff = True
                user.save(update_fields=['is_staff'])
        
            if role_name == 'Seller':
                Tenant = apps.get_model('tenants', 'Tenant')
                
                # JIKA ADMIN MEMILIH GABUNG STAND YANG SUDAH ADA
                if existing_tenant_id:
                    try:
                        tenant = Tenant.objects.get(id=existing_tenant_id)
                        tenant.staff.add(user) # Masukkan akun ini sebagai staff (Misal Shift 2)
                    except Tenant.DoesNotExist:
                        pass
                
                # JIKA ADMIN MEMILIH BUAT STAND BARU
                else:
                    if not stand_name:
                        random_suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
                        stand_name = f"Stand {user.username}-{random_suffix}"
                        
                    new_stand = Tenant.objects.create(name=stand_name, active=True)
                    new_stand.staff.add(user)
                
            return user
    
class UpdateUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email']
        extra_kwargs = {
            'username': {'required': False},
            'email': {'required': False}
        }
        
class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True)
    confirm_password = serializers.CharField(required=True)
    
    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError("Password lama tidak sesuai")
        return value
    
    def validate_new_password(self, value):
        # Menggunakan Django password validator yang sudah didefinisikan di settings.py
        try:
            validate_password(value, user=self.context['request'].user)
        except ValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value
    
    def validate(self, attrs):
        if attrs.get('new_password') != attrs.get('confirm_password'):
            raise serializers.ValidationError({"confirm_password": "Konfirmasi Password tidak sama"})
        return attrs
    
    def save(self, **kwargs):
        """
        Set password baru pada user yang ada di context.
        Jangan mengembalikan password ke response
        """
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save()
        return user
