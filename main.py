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
        
        # Create a weekly plan if you haven't (or use existing ID)
        # For simplicity, we create a subscription directly. 
        # Note: In real Razorpay flow, you need a Plan ID. 
        # Using a dummy or pre-existing plan ID is best.
        # Here we attempt to create one on the fly for the valid logic.
        
        # Hardcoding a plan creation for demo (check if similar plan exists in production logic)
        plan = client.plan.create({
            "period": "weekly",
            "interval": 1,
            "item": {
                "name": "Weekly Pro Plan",
                "amount": 25000,
                "currency": "INR",
                "description": "Weekly subscription for pro features"
            }
        })
        plan_id = plan['id']

        subscription = client.subscription.create({
            "plan_id": plan_id,
            "customer_notify": 1,
            "quantity": 1,
            "total_count": 52,
            "notes": {
                "user_id": user_id
            }
        })

        return jsonify({
            'id': subscription['id'],
            'plan_id': plan_id,
            'status': subscription['status']
        })

    except Exception as e:
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
            # 1. Calculate Expiry (7 Days from now)
            now = datetime.utcnow()
            expiry_date = now + timedelta(days=7)
            
            # 2. Update Supabase via REST API
            update_data = {
                'is_subscribed': True
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
                return jsonify({'status': 'success', 'message': 'Payment verified and Subscription Activated'})
            else:
                return jsonify({'status': 'error', 'message': f'Database update failed: {response.text}'}), 500
        else:
            return jsonify({'status': 'failure', 'message': 'Signature mismatch'}), 400
            
    except Exception as e:
        print(f"Error in verify: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000, debug=True)

