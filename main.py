from flask import Flask, request, jsonify
from flask_cors import CORS
import razorpay
import hmac
import hashlib
import os
from datetime import datetime, timedelta
import requests

app = Flask(__name__)
CORS(app)  # Enable CORS for Flutter app

# Razorpay Config
RAZORPAY_KEY_ID = "rzp_test_Rtu4LYqgDIZbL9"
RAZORPAY_KEY_SECRET = "qlped9HaWH4MhgS5XimF141O"

client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# Supabase Config
SUPABASE_URL = 'https://rvrpsqdrbwfvllelyqhf.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJ2cnBzcWRyYndmdmxsZWx5cWhmIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjUxNTgxOTksImV4cCI6MjA4MDczNDE5OX0.ON2ioqbNJegKOWeGu_eqsgjNxQ6IdHCDuFRqjUfBYHk'

@app.route('/create-subscription', methods=['POST'])
def create_subscription():
    try:
        data = request.json
        user_id = data.get('userId')
        fine_amount = data.get('fineAmount', 0)  # Get fine amount if exists
        
        # Base subscription amount (₹250 = 25000 paise)
        base_amount = 25000
        total_amount = base_amount + (fine_amount * 100)  # Convert fine to paise and add
        
        print(f'Creating subscription for user {user_id}')
        print(f'Base amount: ₹{base_amount/100}, Fine: ₹{fine_amount}, Total: ₹{total_amount/100}')
        
        # Create a weekly plan with the total amount
        plan = client.plan.create({
            "period": "weekly",
            "interval": 1,
            "item": {
                "name": "Weekly Pro Plan" + (f" + Fines" if fine_amount > 0 else ""),
                "amount": int(total_amount),
                "currency": "INR",
                "description": f"Weekly subscription (₹{base_amount/100})" + (f" + outstanding fines (₹{fine_amount})" if fine_amount > 0 else "")
            }
        })
        plan_id = plan['id']

        subscription = client.subscription.create({
            "plan_id": plan_id,
            "customer_notify": 1,
            "quantity": 1,
            "total_count": 52,
            "notes": {
                "user_id": user_id,
                "fine_amount": str(fine_amount) if fine_amount > 0 else "0"
            }
        })

        return jsonify({
            'id': subscription['id'],
            'plan_id': plan_id,
            'status': subscription['status'],
            'fine_amount': fine_amount
        })

    except Exception as e:
        print(f'Error creating subscription: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/verify-payment', methods=['POST'])
def verify_payment():
    try:
        data = request.json
        razorpay_payment_id = data.get('razorpay_payment_id')
        razorpay_subscription_id = data.get('razorpay_subscription_id')
        razorpay_signature = data.get('razorpay_signature')
        user_id = data.get('user_id')

        msg = f"{razorpay_payment_id}|{razorpay_subscription_id}"
        
        generated_signature = hmac.new(
            bytes(RAZORPAY_KEY_SECRET, 'utf-8'),
            bytes(msg, 'utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        if generated_signature == razorpay_signature:
            # Fetch subscription details to get fine amount
            subscription = client.subscription.fetch(razorpay_subscription_id)
            fine_amount = float(subscription.get('notes', {}).get('fine_amount', 0))
            
            print(f'Subscription verified for user {user_id}')
            print(f'Fine amount in subscription: ₹{fine_amount}')
            
            # 1. If fine amount exists, mark fines as paid
            if fine_amount > 0:
                print(f'Paying fines for provider {user_id}, amount: ₹{fine_amount}')
                
                # Call Supabase RPC to pay fines
                headers = {
                    'apikey': SUPABASE_KEY,
                    'Authorization': f'Bearer {SUPABASE_KEY}',
                    'Content-Type': 'application/json'
                }
                
                fine_response = requests.post(
                    f'{SUPABASE_URL}/rest/v1/rpc/pay_provider_fines',
                    json={
                        'p_provider_id': user_id,
                        'p_payment_amount': fine_amount,
                        'p_payment_method': 'razorpay_subscription'
                    },
                    headers=headers
                )
                
                if fine_response.status_code in [200, 204]:
                    print(f'✅ Fines paid successfully for user {user_id}')
                else:
                    print(f'⚠️ Warning: Fine payment failed: {fine_response.text}')
            
            # 2. Calculate Expiry (7 Days from now)
            now = datetime.utcnow()
            expiry_date = now + timedelta(days=7)
            
            # 3. Update Supabase via REST API
            # CRITICAL: Set both old and new subscription fields
            update_data = {
                'is_subscribed': True,
                'subscription_expiry': expiry_date.isoformat(),
                'subscription_status': 'active',  # NEW: Strict status field
                'subscription_start_date': now.isoformat(),  # NEW: Track when subscription started
                'subscription_end_date': expiry_date.isoformat()  # NEW: Strict end date
            }
            
            # Supabase REST API call
            headers = {
                'apikey': SUPABASE_KEY,
                'Authorization': f'Bearer {SUPABASE_KEY}',
                'Content-Type': 'application/json',
                'Prefer': 'return=minimal'
            }
            
            response = requests.patch(
                f'{SUPABASE_URL}/rest/v1/users?id=eq.{user_id}',
                json=update_data,
                headers=headers
            )
            
            if response.status_code in [200, 204]:
                print(f'✅ Subscription activated for user {user_id} until {expiry_date.isoformat()}')
                return jsonify({
                    'status': 'success', 
                    'message': 'Payment verified and Subscription Activated',
                    'fines_paid': fine_amount > 0
                })
            else:
                return jsonify({'status': 'error', 'message': f'Database update failed: {response.text}'}), 500
        else:
            return jsonify({'status': 'failure', 'message': 'Signature mismatch'}), 400
            
    except Exception as e:
        print(f"Error in verify: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/create-fine-payment', methods=['POST'])
def create_fine_payment():
    try:
        data = request.json
        user_id = data.get('userId')
        amount = data.get('amount')  # Amount in rupees
        
        print(f'Creating fine payment for user {user_id}, amount: ₹{amount}')
        
        # Create Razorpay order for fine payment
        order = client.order.create({
            'amount': int(amount * 100),  # Convert to paise
            'currency': 'INR',
            'payment_capture': 1,
            'notes': {
                'user_id': user_id,
                'payment_type': 'fine_payment'
            }
        })
        
        return jsonify({
            'orderId': order['id'],
            'amount': amount
        })
    
    except Exception as e:
        print(f'Error creating fine payment: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/verify-fine-payment', methods=['POST'])
def verify_fine_payment():
    try:
        data = request.json
        razorpay_payment_id = data.get('razorpay_payment_id')
        razorpay_order_id = data.get('razorpay_order_id')
        razorpay_signature = data.get('razorpay_signature')
        user_id = data.get('user_id')
        fine_amount = data.get('fine_amount', 0)
        
        # Verify signature
        msg = f"{razorpay_order_id}|{razorpay_payment_id}"
        
        generated_signature = hmac.new(
            bytes(RAZORPAY_KEY_SECRET, 'utf-8'),
            bytes(msg, 'utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        if generated_signature == razorpay_signature:
            print(f'Fine payment verified for user {user_id}, amount: ₹{fine_amount}')
            
            # Call Supabase RPC to pay fines
            headers = {
                'apikey': SUPABASE_KEY,
                'Authorization': f'Bearer {SUPABASE_KEY}',
                'Content-Type': 'application/json'
            }
            
            fine_response = requests.post(
                f'{SUPABASE_URL}/rest/v1/rpc/pay_provider_fines',
                json={
                    'p_provider_id': user_id,
                    'p_payment_amount': fine_amount,
                    'p_payment_method': 'razorpay'
                },
                headers=headers
            )
            
            if fine_response.status_code in [200, 204]:
                print(f'✅ Fines paid successfully for user {user_id}')
                return jsonify({
                    'status': 'success',
                    'message': 'Fine payment verified and fines marked as paid'
                })
            else:
                return jsonify({
                    'status': 'error',
                    'message': f'Fine payment failed: {fine_response.text}'
                }), 500
        else:
            return jsonify({'status': 'failure', 'message': 'Signature mismatch'}), 400
    
    except Exception as e:
        print(f'Error verifying fine payment: {e}')
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000, debug=True)
