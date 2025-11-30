# tenants/urls.py
from django.urls import path, include
from rest_framework import routers
from rest_framework_nested import routers 
from .views import (
    StandViewSet, 
    MenuItemViewSet,
    VariantGroupViewSet,
    VariantOptionViewSet
)

router = routers.DefaultRouter()
router.register(r'stands', StandViewSet, basename='stand')

stands_router = routers.NestedDefaultRouter(router, r'stands', lookup='stand')
stands_router.register(r'menus', MenuItemViewSet, basename='stand-menus')
stands_router.register(r'variant-groups', VariantGroupViewSet, basename='stand-variant-groups')

groups_router = routers.NestedDefaultRouter(stands_router, r'variant-groups', lookup='group')
groups_router.register(r'options', VariantOptionViewSet, basename='group-options')

urlpatterns = [
    path('', include(router.urls)),
    path('', include(stands_router.urls)),
    path('', include(groups_router.urls)),
]