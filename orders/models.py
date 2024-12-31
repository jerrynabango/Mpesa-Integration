from django.db import models


# Create your models here.
class Order(models.Model):
    customer_name = models.CharField(max_length=100)
    customer_email = models.EmailField()
    customer_phone_number = models.CharField(max_length=15)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    mpesa_transaction_id = models.CharField(max_length=255, null=True,
                                            blank=True)
    status = models.CharField(max_length=50, choices=[('pending', 'Pending'),
                                                      ('paid', 'Paid')],
                              default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Order {self.id} - {self.customer_name}"
