import json
import uuid
from flask import Flask, request, jsonify
from datetime import datetime
from functools import wraps

USERS = {}
COMPANIES = {}
EXPENSES = {}

DEFAULT_APPROVAL_FLOW = [
    {"role": "Manager", "step_name": "Manager Approval"},
    {"role": "Finance", "step_name": "Finance Review"},
    {"role": "Admin", "step_name": "Director Sign-off"}
]

CURRENT_USER_ID = "admin-user-123"

def get_current_user_id():
    """Retrieves the ID of the user performing the request."""
    return CURRENT_USER_ID

def get_user_role(user_id):
    """Fetches the role of a user from the in-memory database."""
    return USERS.get(user_id, {}).get('role')

def require_role(allowed_roles):
    """Decorator to enforce role-based access control (RBAC)."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user_id = get_current_user_id()
            if not user_id:
                return jsonify({"error": "Authentication required."}), 401
            
            user_role = get_user_role(user_id)
            if user_role not in allowed_roles:
                return jsonify({"error": f"Access denied. Required roles: {', '.join(allowed_roles)}"}), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def mock_currency_conversion(from_currency, to_currency, amount):
    """
    Mocks the external API call for currency conversion
    """
    if from_currency == to_currency:
        return amount
    
    mock_rates = {
        "USD": {"EUR": 0.93, "INR": 83.00, "USD": 1.0},
        "EUR": {"USD": 1.08, "INR": 89.00, "EUR": 1.0},
        "INR": {"USD": 0.012, "EUR": 0.011, "INR": 1.0},
    }
    
    try:
        rate = mock_rates[from_currency.upper()][to_currency.upper()]
        converted_amount = round(amount * rate, 2)
        return converted_amount
    except KeyError:
        return amount

def process_next_approval_step(expense_id):
    """
    Handles the sequential approval logic.
    Moves the expense to the next approver in the defined flow.
    """
    expense = EXPENSES.get(expense_id)
    if not expense:
        return {"success": False, "message": "Expense not found."}

    flow = expense['approval_flow']
    current_index = expense['current_approver_index']
    
    if current_index + 1 < len(flow):
        expense['current_approver_index'] += 1
        next_approver_step = flow[expense['current_approver_index']]
        expense['status'] = f"Pending ({next_approver_step['step_name']})"
        return {"success": True, "message": f"Moved to next step: {next_approver_step['step_name']}"}
    else:
        expense['status'] = "Approved"
        return {"success": True, "message": "Expense fully approved."}

def check_can_approve(user_id, expense):
    """
    Checks if the current user has the authority to approve this expense step.
    """
    if expense['status'] in ["Approved", "Rejected"]:
        return False, "This expense is already finalized."

    user_role = get_user_role(user_id)
    company_id = USERS.get(user_id, {}).get('company_id')
    
    if user_role == "Admin":
        return True, None
    
    flow = expense['approval_flow']
    current_index = expense['current_approver_index']
    
    if current_index < len(flow):
        required_role = flow[current_index]['role']
        
        if user_role == required_role:
            if current_index == 0 and required_role == "Manager":
                employee_id = expense['user_id']
                employee_data = USERS.get(employee_id, {})
                
                if employee_data.get('manager_id') == user_id:
                     return True, None
                else:
                    return False, f"You are not the assigned manager for this employee."
            
            return True, None
    
    return False, "You do not have the required role/authority for the current approval step."

def initialize_database():
    """Sets up initial company and admin user as per the PDF's 'On first login/signup' rule."""
    global CURRENT_USER_ID
    
    company_id = str(uuid.uuid4())
    admin_id = CURRENT_USER_ID
    
    COMPANIES[company_id] = {
        "id": company_id,
        "name": "Acme Global Inc.",
        "default_currency": "USD",
        "approval_config": DEFAULT_APPROVAL_FLOW
    }
    
    USERS[admin_id] = {
        "id": admin_id,
        "company_id": company_id,
        "name": "Admin User",
        "role": "Admin",
        "manager_id": None
    }
    
    manager_id = str(uuid.uuid4())
    employee_id = str(uuid.uuid4())
    
    USERS[manager_id] = {
        "id": manager_id,
        "company_id": company_id,
        "name": "Jane Manager",
        "role": "Manager",
        "manager_id": admin_id
    }
    
    USERS[employee_id] = {
        "id": employee_id,
        "company_id": company_id,
        "name": "Tom Employee",
        "role": "Employee",
        "manager_id": manager_id
    }

    global CURRENT_USER_ID
    CURRENT_USER_ID = employee_id
    
    print(f"--- Initialization Complete ---")
    print(f"Admin User ID: {admin_id}")
    print(f"Manager User ID: {manager_id}")
    print(f"Employee User ID (Current User): {employee_id}")
    print(f"Company ID: {company_id}\n")

app = Flask(__name__)

@app.route('/api/auth/status', methods=['GET'])
def get_auth_status():
    """Endpoint to check the current user's role and company."""
    user_id = get_current_user_id()
    user_data = USERS.get(user_id)
    if not user_data:
        return jsonify({"user_id": user_id, "role": "Unauthenticated"}), 401
    
    company = COMPANIES.get(user_data['company_id'])
    
    return jsonify({
        "user_id": user_id,
        "name": user_data['name'],
        "role": user_data['role'],
        "company_currency": company['default_currency']
    })

@app.route('/api/admin/users', methods=['POST'])
@require_role(["Admin"])
def create_user():
    """Admin endpoint to create new Employees/Managers and set relationships."""
    data = request.json
    
    required_fields = ['name', 'role', 'manager_id']
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Missing required fields: name, role, manager_id"}), 400
        
    if data['role'] not in ['Employee', 'Manager', 'Finance']:
        return jsonify({"error": "Invalid role specified."}), 400
        
    admin_id = get_current_user_id()
    company_id = USERS[admin_id]['company_id']
    new_user_id = str(uuid.uuid4())
    
    USERS[new_user_id] = {
        "id": new_user_id,
        "company_id": company_id,
        "name": data['name'],
        "role": data['role'],
        "manager_id": data['manager_id'] or None
    }
    
    return jsonify({"message": f"User {data['name']} created.", "user_id": new_user_id}), 201

@app.route('/api/expenses', methods=['POST'])
@require_role(["Employee"])
def submit_expense():
    """Employee endpoint to submit a new expense claim."""
    data = request.json
    user_id = get_current_user_id()
    
    required_fields = ['amount', 'currency', 'category', 'description', 'date']
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Missing required fields: amount, currency, category, description, date"}), 400
    
    company_id = USERS[user_id]['company_id']
    company = COMPANIES[company_id]
    
    try:
        amount = float(data['amount'])
        converted_amount = mock_currency_conversion(data['currency'], company['default_currency'], amount)
    except ValueError:
        return jsonify({"error": "Invalid amount format."}), 400
    
    expense_id = str(uuid.uuid4())
    
    EXPENSES[expense_id] = {
        "id": expense_id,
        "user_id": user_id,
        "company_id": company_id,
        "amount": amount,
        "currency": data['currency'],
        "converted_amount": converted_amount,
        "company_currency": company['default_currency'],
        "category": data['category'],
        "description": data['description'],
        "date": data['date'],
        "status": "Pending (Manager Approval)",
        "approval_flow": company['approval_config'],
        "current_approver_index": 0,
        "history": []
    }
    
    return jsonify({
        "message": "Expense submitted successfully.", 
        "expense_id": expense_id,
        "pending_step": EXPENSES[expense_id]['approval_flow'][0]['step_name'],
        "amount_in_company_currency": f"{converted_amount} {company['default_currency']}"
    }), 201

@app.route('/api/expenses/me', methods=['GET'])
@require_role(["Employee", "Manager", "Admin"])
def view_my_expenses():
    """Employee/Manager endpoint to view their own expense history."""
    user_id = get_current_user_id()
    
    user_expenses = [
        expense for expense in EXPENSES.values() 
        if expense['user_id'] == user_id
    ]
    
    return jsonify(user_expenses)

@app.route('/api/expenses/pending', methods=['GET'])
@require_role(["Manager", "Admin", "Finance"])
def view_pending_expenses():
    """Manager/Admin endpoint to view expenses waiting for their approval."""
    user_id = get_current_user_id()
    user_role = get_user_role(user_id)
    company_id = USERS[user_id]['company_id']
    
    pending_list = []
    
    for expense in EXPENSES.values():
        if expense['company_id'] != company_id or expense['status'] in ["Approved", "Rejected"]:
            continue
            
        current_index = expense['current_approver_index']
        
        if current_index < len(expense['approval_flow']):
            required_role = expense['approval_flow'][current_index]['role']
            
            if user_role == "Admin":
                pending_list.append(expense)
                continue
            
            if user_role == required_role:
                if required_role == "Manager":
                    employee_id = expense['user_id']
                    if USERS.get(employee_id, {}).get('manager_id') == user_id:
                        pending_list.append(expense)
                else:
                    pending_list.append(expense)

    return jsonify(pending_list)

@app.route('/api/expenses/<expense_id>/approve', methods=['POST'])
@require_role(["Manager", "Admin", "Finance"])
def approve_expense(expense_id):
    """Approves the current step of an expense."""
    user_id = get_current_user_id()
    expense = EXPENSES.get(expense_id)
    comment = request.json.get('comment', 'Approved.')
    
    if not expense:
        return jsonify({"error": "Expense not found."}), 404
        
    can_approve, reason = check_can_approve(user_id, expense)
    if not can_approve:
        return jsonify({"error": reason}), 403
        
    current_step_name = expense['approval_flow'][expense['current_approver_index']]['step_name']
    expense['history'].append({
        "timestamp": datetime.now().isoformat(),
        "action": "Approved",
        "step": current_step_name,
        "approver_id": user_id,
        "comment": comment
    })
    
    result = process_next_approval_step(expense_id)
    
    return jsonify({
        "message": f"Expense {expense_id} approved at '{current_step_name}'. {result['message']}",
        "new_status": expense['status']
    })

@app.route('/api/expenses/<expense_id>/reject', methods=['POST'])
@require_role(["Manager", "Admin", "Finance"])
def reject_expense(expense_id):
    """Rejects the expense, stopping the flow."""
    user_id = get_current_user_id()
    expense = EXPENSES.get(expense_id)
    comment = request.json.get('comment', 'Rejected.')
    
    if not expense:
        return jsonify({"error": "Expense not found."}), 404
        
    can_approve, reason = check_can_approve(user_id, expense)
    if not can_approve:
        return jsonify({"error": reason}), 403
        
    current_step_name = expense['approval_flow'][expense['current_approver_index']]['step_name']
    expense['status'] = "Rejected"
    
    expense['history'].append({
        "timestamp": datetime.now().isoformat(),
        "action": "Rejected",
        "step": current_step_name,
        "approver_id": user_id,
        "comment": comment
    })
    
    return jsonify({
        "message": f"Expense {expense_id} rejected at '{current_step_name}'. Status finalized.",
        "new_status": expense['status']
    })

if __name__ == '__main__':
    initialize_database()
    print("Flask App running at http://127.0.0.1:5000")
    print("Use tool like Postman or a client to test the API endpoints.")
    print("Example: POST http://127.0.0.1:5000/api/expenses (with JSON body) to submit an expense.")
    app.run(debug=True, use_reloader=False)