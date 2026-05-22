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
    # Ubah ini dari CharField biasa menjadi SerializerMethodField
    # tujuannya agar kita bisa memanipulasi teksnya (jadi lowercase)
    role = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'role', 'first_name', 'last_name']

    def get_role(self, obj):
        # Ambil group pertama user
        group = obj.groups.first()
        if group:
            # Kembalikan nama group dalam HURUF KECIL (lower)
            # Contoh: "Cashier" menjadi "cashier"
            return group.name.lower()
        return None

class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    # 1. Ganti ChoiceField menjadi CharField biasa
    role = serializers.CharField(write_only=True)
    
    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'role']

    # 2. Tambahkan fungsi validasi khusus untuk kolom 'role'
    def validate_role(self, value):
        valid_roles = ['admin', 'seller', 'cashier']
        
        # Cek apakah input (yang sudah diubah ke huruf kecil) ada di daftar valid
        if value.lower() not in valid_roles:
            raise serializers.ValidationError(f"'{value}' bukan pilihan role yang valid.")
            
        # Kembalikan nilai dengan huruf depan kapital (contoh: 'admin' jadi 'Admin')
        return value.capitalize()

    def create(self, validated_data):
        with transaction.atomic():
            # role_name di sini SUDAH PASTI menjadi 'Admin', 'Seller', atau 'Cashier'
            # berkat proses pembersihan di fungsi validate_role di atas.
            role_name = validated_data.pop('role')
            
            user = User.objects.create_user(**validated_data)
            group, _ = Group.objects.get_or_create(name=role_name)
            user.groups.add(group)
            
            if role_name == 'Admin':
                user.is_staff = True
                user.save(update_fields=['is_staff'])
        
            if role_name == 'Seller':
                Tenant = apps.get_model('tenants', 'Tenant')
                random_suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
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
