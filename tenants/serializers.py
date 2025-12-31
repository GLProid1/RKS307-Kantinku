from rest_framework import serializers
from .models import Tenant, MenuItem, VariantGroup, VariantOption

class VariantGroupCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = VariantGroup
        fields = ['id', 'name']
        # 'tenant' akan di-set otomatis dari URL
        
class VariantOptionCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = VariantOption
        fields = ['name', 'price']

class VariantOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = VariantOption
        fields = ['id', 'name', 'price']

class VariantGroupSerializer(serializers.ModelSerializer):
    options = VariantOptionSerializer(many=True, read_only=True)
    class Meta:
        model = VariantGroup
        fields = ['id', 'name', 'options']

class MenuItemSerializer(serializers.ModelSerializer):
    variant_groups = VariantGroupSerializer(many=True, read_only=True)
    
    # 1. Field 'tenant' asli (tetap ada untuk kompatibilitas)
    tenant = serializers.PrimaryKeyRelatedField(read_only=True)
    
    # 2. TAMBAHAN PENTING: Alias 'tenant_id' agar Frontend lebih aman membacanya
    tenant_id = serializers.PrimaryKeyRelatedField(source='tenant', read_only=True)

    # 2. Nama Stand untuk ditampilkan di Card
    tenant_name = serializers.CharField(source='tenant.name', read_only=True)
    
    # 3. Helper URL Gambar
    imageUrl = serializers.URLField(source='image.url', read_only=True)

    class Meta:
        model = MenuItem
        fields = [
            'id', 
            'tenant',      # Output: 1
            'tenant_id',
            'tenant_name',# Output: 1 (Sama, tapi nama field lebih jelas)
            'name', 
            'price', 
            'available', 
            'description', 
            'image', 
            'imageUrl', 
            'category', 
            'stock', 
            'variant_groups'
        ]
class StandSerializer(serializers.ModelSerializer):
    # Field baru untuk mencocokkan komponen frontend StandCard.jsx
    status = serializers.SerializerMethodField()
    seller = serializers.SerializerMethodField()
    imageUrl = serializers.URLField(source='image.url', read_only=True)

    class Meta:
        model = Tenant
        fields = ['id', 'name', 'description', 'active', 'image', 'imageUrl', 'status', 'seller']
        extra_kwargs = {
            # Membuat field 'image' tidak wajib saat melakukan update
            'image': {'required': False}
        }

    def get_status(self, obj):
        """Mengonversi boolean 'active' menjadi string 'Open'/'Closed'."""
        return "Open" if obj.active else "Closed"

    def get_seller(self, obj):
        """Mengambil nama staf pertama yang terkait, atau nilai default."""
        first_staff = obj.staff.first()
        return first_staff.username if first_staff else "N/A"
