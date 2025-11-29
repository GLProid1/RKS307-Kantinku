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
    tenant = serializers.PrimaryKeyRelatedField(read_only=True)
    
    # --- TAMBAHKAN BARIS INI ---
    imageUrl = serializers.URLField(source='image.url', read_only=True)
    # --- AKHIR TAMBAHAN ---

    class Meta:
        model = MenuItem
        fields = [
            'id', 'tenant', 'name', 'price', 'available', 'description', 
            'image', 'imageUrl', # <-- Tambahkan 'imageUrl' di sini
            'category', 'stock', 'variant_groups'
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
