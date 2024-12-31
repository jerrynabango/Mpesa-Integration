from django.urls import path
from . import views

urlpatterns = [
    path('create-order/', views.create_order, name='create_order'),
    path('lipa-na-mpesa/<int:order_id>/', views.lipa_na_mpesa,
         name='lipa_na_mpesa'),
]
