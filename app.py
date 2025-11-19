from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import re
import secrets
import traceback

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
CORS(app)

BASE_URL = "https://lis-hac.eschoolplus.powerschool.com"

def create_session_and_login(username, password):
    """Create a session and login to HAC"""
    sess = requests.Session()
    login_url = f"{BASE_URL}/HomeAccess/Account/LogOn"
    
    # Get login page
    response = sess.get(login_url)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Prepare login data
    login_data = {
        'Database': '10',
        'LogOnDetails.UserName': username,
        'LogOnDetails.Password': password
    }
    
    # Extract hidden fields
    login_form = soup.find('form')
    if login_form:
        hidden_inputs = login_form.find_all('input', type='hidden')
        for hidden in hidden_inputs:
            name = hidden.get('name')
            value = hidden.get('value', '')
            if name:
                login_data[name] = value
    
    # Login
    login_response = sess.post(login_url, data=login_data, allow_redirects=True)
    
    # Check if login successful
    if 'LogOn' in login_response.url:
        return None, "Invalid username or password"
    
    return sess, None

def get_grades_data(sess):
    """Get all grades from HAC"""
    grades_url = f"{BASE_URL}/HomeAccess/Content/Student/Assignments.aspx"
    grades_response = sess.get(grades_url)
    soup = BeautifulSoup(grades_response.text, 'html.parser')
    
    grades = []
    classes = soup.find_all('div', class_='AssignmentClass')
    
    for idx, cls in enumerate(classes):
        # Get course name
        course_name_elem = cls.find('a', class_='sg-header-heading')
        if course_name_elem:
            course_name = course_name_elem.get_text(strip=True)
            
            # Look for average/grade
            avg_elem = cls.find('span', class_='sg-header-heading sg-right')
            if avg_elem:
                grade_text = avg_elem.get_text(strip=True)
                grade_text = grade_text.replace('Cycle Average', '').strip()
                
                if grade_text:
                    # Use index as course_id since there's no unique identifier
                    grades.append({
                        'name': course_name,
                        'grade': grade_text,
                        'course_id': str(idx)
                    })
    
    return grades

def get_assignments_for_class(sess, course_index):
    """Get all assignments for a specific class"""
    # The assignments are already on the same page, we need to find the right section
    grades_url = f"{BASE_URL}/HomeAccess/Content/Student/Assignments.aspx"
    grades_response = sess.get(grades_url)
    soup = BeautifulSoup(grades_response.text, 'html.parser')
    
    assignments = []
    
    # Find all assignment class divs
    classes = soup.find_all('div', class_='AssignmentClass')
    
    # Convert course_index to int and get the specific class
    try:
        idx = int(course_index)
        if idx < len(classes):
            cls = classes[idx]
            
            # Get assignments from this class
            assignment_table = cls.find('table', class_='sg-asp-table')
            
            if assignment_table:
                rows = assignment_table.find_all('tr', class_='sg-asp-table-data-row')
                
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) >= 4:
                        date_due = cells[0].get_text(strip=True)
                        date_assigned = cells[1].get_text(strip=True)
                        assignment_name = cells[2].get_text(strip=True)
                        category = cells[3].get_text(strip=True)
                        score = cells[4].get_text(strip=True) if len(cells) > 4 else 'N/A'
                        
                        assignments.append({
                            'date_due': date_due,
                            'date_assigned': date_assigned,
                            'name': assignment_name,
                            'category': category,
                            'score': score
                        })
    except (ValueError, IndexError):
        pass
    
    return assignments

# Store sessions temporarily (in production, use proper session management)
user_sessions = {}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({'error': 'Username and password required'}), 400
        
        sess, error = create_session_and_login(username, password)
        
        if error:
            return jsonify({'error': error}), 401
        
        # Store session
        session_id = secrets.token_hex(16)
        user_sessions[session_id] = sess
        
        return jsonify({'session_id': session_id, 'message': 'Login successful'})
    except Exception as e:
        print(f"Login error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/api/grades', methods=['GET'])
def grades():
    session_id = request.headers.get('X-Session-ID')
    
    if not session_id or session_id not in user_sessions:
        return jsonify({'error': 'Invalid session'}), 401
    
    sess = user_sessions[session_id]
    
    try:
        grades_data = get_grades_data(sess)
        
        # Calculate overall average
        total = 0
        count = 0
        for grade in grades_data:
            grade_text = grade['grade'].replace('%', '').strip()
            match = re.search(r'(\d+\.?\d*)', grade_text)
            if match:
                total += float(match.group(1))
                count += 1
        
        overall_avg = round(total / count, 2) if count > 0 else 0
        
        return jsonify({
            'grades': grades_data,
            'overall_average': overall_avg
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/assignments/<course_id>', methods=['GET'])
def assignments(course_id):
    session_id = request.headers.get('X-Session-ID')
    
    if not session_id or session_id not in user_sessions:
        return jsonify({'error': 'Invalid session'}), 401
    
    sess = user_sessions[session_id]
    
    try:
        assignments_data = get_assignments_for_class(sess, course_id)
        return jsonify({'assignments': assignments_data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run()
