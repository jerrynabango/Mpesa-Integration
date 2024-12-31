from django.shortcuts import render, redirect
from django.conf import settings
from django.http import JsonResponse
from .models import Order
from requests.auth import HTTPBasicAuth
from django.views.decorators.csrf import csrf_exempt
import datetime
import base64
import requests
import logging
import json
from django.shortcuts import get_object_or_404


# M-Pesa API credentials
LIPA_NA_MPESA_SHORTCODE = settings.MPESA_LIPA_NA_MPESA_SHORTCODE
LIPA_NA_MPESA_PASSKEY = settings.MPESA_LIPA_NA_MPESA_PASSKEY
LIPA_NA_MPESA_CALLBACK_URL = settings.MPESA_CALLBACK_URL
LIPA_NA_MPESA_LIVE = settings.MPESA_LIPA_NA_MPESA_LIVE
CONSUMER_KEY = settings.MPESA_CONSUMER_KEY
CONSUMER_SECRET = settings.MPESA_CONSUMER_SECRET

# Configure the logger
logger = logging.getLogger(__name__)


# Mpesa_Token
def get_mpesa_token():
    api_url = 'https://api.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials'
    if not LIPA_NA_MPESA_LIVE:
        api_url = 'https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials'

    auth = HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET)
    response = requests.get(api_url, auth=auth)
    response.raise_for_status()
    json_response = response.json()
    return json_response['access_token']


# Create order view
def create_order(request):
    if request.method == 'POST':
        customer_name = request.POST['customer_name']
        customer_email = request.POST['customer_email']
        customer_phone_number = request.POST['customer_phone_number']
        amount = request.POST['amount']

        order = Order.objects.create(
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone_number=customer_phone_number,
            amount=amount
        )
        return redirect('lipa_na_mpesa', order_id=order.id)
    return render(request, 'create_order.html')


# Payment processing view
def lipa_na_mpesa(request, order_id):
    # Fetching the order from the database
    order = get_object_or_404(Order, id=order_id)

    # Generating M-Pesa API token
    try:
        token = get_mpesa_token()
    except Exception as e:
        logger.error("Error fetching M-Pesa token: %s", e, exc_info=True)
        return JsonResponse({'error': 'Failed to authenticate with M-Pesa'},
                            status=500)

    # M-Pesa API headers
    headers = {
        'Authorization': f'Bearer {token}'
    }

    # M-Pesa API endpoint
    api_url = 'https://api.safaricom.co.ke/mpesa/stkpush/v1/processrequest' if settings.MPESA_LIPA_NA_MPESA_LIVE else 'https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest'

    # Generating timestamp and password for the STK request
    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    password = base64.b64encode(
        (settings.MPESA_LIPA_NA_MPESA_SHORTCODE + settings.MPESA_LIPA_NA_MPESA_PASSKEY + timestamp).encode()
    ).decode()

    # STK push payload
    payload = {
        "BusinessShortCode": settings.MPESA_LIPA_NA_MPESA_SHORTCODE,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": order.amount,
        "PartyA": order.customer_phone_number,
        "PartyB": settings.MPESA_LIPA_NA_MPESA_SHORTCODE,
        "PhoneNumber": order.customer_phone_number,
        "CallBackURL": settings.MPESA_CALLBACK_URL,
        "AccountReference": f"Order-{order.id}",
        "TransactionDesc": f"Payment for order {order.id}"
    }

    try:
        # Sending the STK push request
        response = requests.post(api_url, json=payload, headers=headers)

        if response.status_code == 200:
            # Processing the response from M-Pesa
            response_data = response.json()
            logger.info("STK Push Request Successful: %s", response_data)

            # Saving the transaction ID in the order
            order.mpesa_transaction_id = response_data.get('MerchantRequestID', '')
            order.status = 'pending'
            order.save()

            # Redirecting to a success page
            return redirect(f"/payment-success/{order.id}")

        else:
            # Handling M-Pesa API errors
            logger.error("STK Push Request Failed: %s", response.text)
            return JsonResponse({'error': 'Payment initiation failed',
                                 'details': response.json()}, status=400)

    except Exception as e:
        # Handling request exceptions
        logger.error("Error during STK Push request: %s", e, exc_info=True)
        return JsonResponse({'error': 'An error occurred while processing payment'}, status=500)


# M-Pesa callback view
@csrf_exempt
def mpesa_callback(request):
    if request.method != 'POST':
        logger.error("Invalid request method: %s", request.method)
        return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Invalid request method'})

    try:
        # Decoding and parsing the JSON callback data
        callback_data = json.loads(request.body)
        body = callback_data.get('Body', {})
        stk_callback = body.get('stkCallback', {})

        # Validating necessary fields
        if not stk_callback:
            logger.error("Missing stkCallback data in callback")
            return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Missing callback data'})

        # Extracting callback data
        result_code = stk_callback.get('ResultCode')
        result_desc = stk_callback.get('ResultDesc', '')
        merchant_request_id = stk_callback.get('MerchantRequestID', '')

        # Handling transaction results
        order = Order.objects.filter(mpesa_transaction_id=merchant_request_id).first()
        if order:
            if result_code == 0:
                metadata = stk_callback.get('CallbackMetadata', {}).get('Item', [])
                amount = next((item['Value'] for item in metadata if item['Name'] == 'Amount'), None)
                transaction_id = next((item['Value'] for item in metadata if item['Name'] == 'MpesaReceiptNumber'), None)

                # Updating order
                order.status = 'paid'
                order.mpesa_transaction_id = transaction_id
                order.save()
                logger.info("Payment successful for Order ID %s: Amount %s, Transaction ID %s", order.id, amount, transaction_id)
            else:
                order.status = 'pending'
                logger.warning("Transaction failed for Order ID %s: %s",
                               order.id, result_desc)
        else:
            logger.error("Order not found for MerchantRequestID: %s",
                         merchant_request_id)
            return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Order not found'})

        return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})

    except Exception as e:
        logger.error("Error processing callback: %s", e, exc_info=True)
        return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Error processing callback'})
