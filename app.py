from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import re
import secrets
import traceback
import random
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
CORS(app, origins=["http://localhost:5173", "http://127.0.0.1:5173"], supports_credentials=True)

BASE_URL = "https://lis-hac.eschoolplus.powerschool.com"

def create_session_and_login(username, password):
    sess = requests.Session()
    login_url = f"{BASE_URL}/HomeAccess/Account/LogOn"
    
    response = sess.get(login_url)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    login_data = {
        'Database': '10',
        'LogOnDetails.UserName': username,
        'LogOnDetails.Password': password
    }
    
    login_form = soup.find('form')
    if login_form:
        hidden_inputs = login_form.find_all('input', type='hidden')
        for hidden in hidden_inputs:
            name = hidden.get('name')
            value = hidden.get('value', '')
            if name:
                login_data[name] = value
    
    login_response = sess.post(login_url, data=login_data, allow_redirects=True)
    
    if 'LogOn' in login_response.url:
        return None, "Invalid username or password"
    
    return sess, None

def calculate_gpa_for_grade(grade_percent, course_name):
    import math
    rounded_grade = math.floor(grade_percent + 0.5) if (grade_percent % 1) == 0.5 else round(grade_percent)
    
    if 'AP' in course_name.upper():
        base_gpa = 6.0
    elif 'ADV' in course_name.upper() or 'ADVANCED' in course_name.upper():
        base_gpa = 5.5
    else:
        base_gpa = 5.0
    
    points_below_100 = 100 - rounded_grade
    gpa = base_gpa - (points_below_100 * 0.1)
    
    return max(0, min(gpa, base_gpa))

def get_category_weights_internal(cls):
    weights = {}
    tables = cls.find_all('table', class_='sg-asp-table')
    
    for table in tables:
        header_row = table.find('tr', class_='sg-asp-table-header-row')
        if header_row:
            headers = [th.get_text(strip=True) for th in header_row.find_all(['th', 'td'])]
            # Look for Category and Weight headers
            if any('Category' in h for h in headers) and any('Weight' in h for h in headers):
                rows = table.find_all('tr', class_='sg-asp-table-data-row')
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) >= 2:
                        cat_name = cells[0].get_text(strip=True)
                        weight_text = cells[1].get_text(strip=True)
                        try:
                            # Remove % and convert to float
                            weight_val = float(weight_text.replace('%', '').strip())
                            weights[cat_name] = weight_val
                        except ValueError:
                            pass
                return weights
    return {}

def get_assignments_for_class_internal(cls):
    assignments = []
    
    # Try to find the assignments table specifically
    tables = cls.find_all('table', class_='sg-asp-table')
    assignment_table = None
    
    for table in tables:
        header_row = table.find('tr', class_='sg-asp-table-header-row')
        if header_row:
            headers = [th.get_text(strip=True) for th in header_row.find_all(['th', 'td'])]
            if any('Assignment' in h for h in headers) and any('Score' in h for h in headers):
                assignment_table = table
                break
    
    # Fallback to first table if specific one not found
    if not assignment_table and tables:
        assignment_table = tables[0]
    
    if assignment_table:
        rows = assignment_table.find_all('tr', class_='sg-asp-table-data-row')
        
        for row in rows:
            cells = row.find_all('td')
            if len(cells) >= 4:
                date_due = cells[0].get_text(strip=True)
                date_assigned = cells[1].get_text(strip=True)
                assignment_name = cells[2].get_text(strip=True)
                category = cells[3].get_text(strip=True)
                score_text = cells[4].get_text(strip=True) if len(cells) > 4 else 'N/A'
                
                earned = None
                max_points = 100.0
                
                if '/' in score_text:
                    try:
                        parts = score_text.split('/')
                        earned = float(parts[0])
                        max_points = float(parts[1])
                    except ValueError:
                        pass
                elif score_text and score_text != 'N/A':
                    try:
                        # Extract number from string like "95.00" or "95%"
                        match = re.search(r'(\d+\.?\d*)', score_text)
                        if match:
                            earned = float(match.group(1))
                    except ValueError:
                        pass

                assignments.append({
                    'date_due': date_due,
                    'date_assigned': date_assigned,
                    'name': assignment_name,
                    'category': category,
                    'score': score_text,
                    'earned': earned,
                    'max_points': max_points
                })
    
    return assignments

def get_grades_data(sess):
    grades_url = f"{BASE_URL}/HomeAccess/Content/Student/Assignments.aspx"
    grades_response = sess.get(grades_url)
    soup = BeautifulSoup(grades_response.text, 'html.parser')
    
    grades = []
    classes = soup.find_all('div', class_='AssignmentClass')
    
    for idx, cls in enumerate(classes):
        course_name_elem = cls.find('a', class_='sg-header-heading')
        if course_name_elem:
            course_name = course_name_elem.get_text(strip=True)
            
            avg_elem = cls.find('span', class_='sg-header-heading sg-right')
            grade_text = ''
            numeric_grade = None
            course_gpa = None
            
            if avg_elem:
                grade_text = avg_elem.get_text(strip=True)
                grade_text = grade_text.replace('Cycle Average', '').strip()
                
                if grade_text:
                    grade_match = re.search(r'(\d+\.?\d*)', grade_text)
                    
                    if grade_match:
                        numeric_grade = float(grade_match.group(1))
                        course_gpa = round(calculate_gpa_for_grade(numeric_grade, course_name), 2)
            
            if not grade_text:
                grade_text = 'No Grade Yet'
            
            assignments = get_assignments_for_class_internal(cls)
            weights = get_category_weights_internal(cls)
            
            grades.append({
                'name': course_name,
                'grade': grade_text,
                'numeric_grade': numeric_grade,
                'gpa': course_gpa,
                'course_id': str(idx),
                'assignments': assignments,
                'weights': weights
            })
    
    return grades

def get_assignments_for_class(sess, course_index):
    grades_url = f"{BASE_URL}/HomeAccess/Content/Student/Assignments.aspx"
    grades_response = sess.get(grades_url)
    soup = BeautifulSoup(grades_response.text, 'html.parser')
    
    assignments = []
    
    classes = soup.find_all('div', class_='AssignmentClass')
    
    try:
        idx = int(course_index)
        if idx < len(classes):
            cls = classes[idx]
            
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

user_sessions = {}
user_credentials = {}
saved_username = None
saved_password = None

# Session cleanup - remove sessions older than 2 hours
session_timestamps = {}

def cleanup_old_sessions():
    """Remove sessions older than 2 hours"""
    current_time = datetime.now()
    expired_sessions = []
    for session_id, timestamp in session_timestamps.items():
        if current_time - timestamp > timedelta(hours=2):
            expired_sessions.append(session_id)
    
    for session_id in expired_sessions:
        user_sessions.pop(session_id, None)
        session_timestamps.pop(session_id, None)

def validate_session(session_id):
    """Validate session and update timestamp"""
    global saved_username, saved_password
    
    if not session_id:
        return False
        
    if session_id not in user_sessions:
        # Try to re-login if we have credentials
        username_to_use = None
        password_to_use = None
        
        if session_id in user_credentials:
            username_to_use = user_credentials[session_id]['username']
            password_to_use = user_credentials[session_id]['password']
        elif saved_username and saved_password:
            username_to_use = saved_username
            password_to_use = saved_password
            
        if username_to_use and password_to_use:
            try:
                sess, error = create_session_and_login(username_to_use, password_to_use)
                
                if not error and sess:
                    user_sessions[session_id] = sess
                    # Ensure credentials are saved for this session
                    if session_id not in user_credentials:
                        user_credentials[session_id] = {'username': username_to_use, 'password': password_to_use}
                    
                    session_timestamps[session_id] = datetime.now()
                    return True
            except Exception as e:
                print(f"Auto-login failed: {str(e)}")
        return False

    # Update timestamp for active session
    session_timestamps[session_id] = datetime.now()
    # Cleanup old sessions periodically
    if len(session_timestamps) % 10 == 0:
        cleanup_old_sessions()
    return True

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'API endpoint not found'}), 404
@app.route('/api/login', methods=['POST'])
def login():
    global saved_username, saved_password
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({'error': 'Username and password required'}), 400
        
        sess, error = create_session_and_login(username, password)
        
        if error:
            return jsonify({'error': error}), 401
        
        session_id = secrets.token_hex(16)
        user_sessions[session_id] = sess
        user_credentials[session_id] = {'username': username, 'password': password}
        session_timestamps[session_id] = datetime.now()
        
        # Save to global variables for auto-relogin
        saved_username = username
        saved_password = password
        
        return jsonify({'session_id': session_id, 'message': 'Login successful'})
        
        if not username or not password:
            return jsonify({'error': 'Username and password required'}), 400
        
        sess, error = create_session_and_login(username, password)
        
        if error:
            return jsonify({'error': error}), 401
        
        session_id = secrets.token_hex(16)
        user_sessions[session_id] = sess
        user_credentials[session_id] = {'username': username, 'password': password}
        session_timestamps[session_id] = datetime.now()
        
        return jsonify({'session_id': session_id, 'message': 'Login successful'})
    except Exception as e:
        print(f"Login error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/api/grades', methods=['GET'])
def grades():
    session_id = request.headers.get('X-Session-ID')
    
    if not validate_session(session_id):
        return jsonify({'error': 'Session expired or invalid. Please log in again.'}), 401
    
    sess = user_sessions[session_id]
    
    try:
        grades_data = get_grades_data(sess)
        
        total = 0
        count = 0
        for grade in grades_data:
            if grade['numeric_grade']:
                total += grade['numeric_grade']
                count += 1
        
        overall_avg = round(total / count, 2) if count > 0 else 0
        
        highlighted_course = None
        if grades_data:
            valid_courses = [g for g in grades_data if g['numeric_grade'] is not None]
            if valid_courses:
                highlighted_course = random.choice(valid_courses)
        
        return jsonify({
            'grades': grades_data,
            'overall_average': overall_avg,
            'highlighted_course': highlighted_course
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/calculate-gpa', methods=['POST'])
def calculate_gpa():
    session_id = request.headers.get('X-Session-ID')
    
    if not validate_session(session_id):
        return jsonify({'error': 'Session expired or invalid. Please log in again.'}), 401
    
    try:
        data = request.json
        selected_course_ids = data.get('selected_courses', [])
        excluded_course_names = data.get('excluded_courses', [])  # Course names to exclude from all cycles
        
        sess = user_sessions[session_id]
        
        # Get current courses
        grades_data = get_grades_data(sess)
        current_course_gpas = []
        for grade in grades_data:
            if grade['course_id'] in selected_course_ids and grade['gpa'] is not None:
                current_course_gpas.append(grade['gpa'])
        
        # Automatically fetch report card data for past cycles
        past_cycle_gpas = []
        past_cycles_detail = []
        all_unique_courses = set()
        
        try:
            grades_url = f"{BASE_URL}/HomeAccess/Content/Student/ReportCards.aspx"
            grades_response = sess.get(grades_url)
            soup = BeautifulSoup(grades_response.text, 'html.parser')
            
            dropdown = soup.find('select', id='plnMain_ddlRCRuns')
            
            if dropdown:
                options = dropdown.find_all('option')
                
                for option in options:
                    parts = option['value'].split('-')
                    rcrun = parts[0] if len(parts) >= 2 else option['value']
                    cycle_name = option.get_text(strip=True)
                    
                    cycle_url = f"{grades_url}?RCRun={rcrun}"
                    cycle_response = sess.get(cycle_url)
                    cycle_soup = BeautifulSoup(cycle_response.text, 'html.parser')
                    
                    report_card_table = cycle_soup.find('table', id='plnMain_dgReportCard')
                    
                    if report_card_table:
                        cycle_courses = []
                        rows = report_card_table.find_all('tr', class_='sg-asp-table-data-row')
                        
                        for row in rows:
                            cells = row.find_all('td')
                            if len(cells) >= 8:
                                course_link = cells[1].find('a')
                                if course_link:
                                    course_name = course_link.get_text(strip=True)
                                else:
                                    course_name = cells[1].get_text(strip=True)
                                
                                # Track all unique course names
                                all_unique_courses.add(course_name)
                                
                                # Skip if course is in exclusion list
                                if course_name in excluded_course_names:
                                    continue
                                
                                grade_found = None
                                for i in range(7, min(len(cells), 22)):
                                    cell_text = cells[i].get_text(strip=True)
                                    if cell_text and re.match(r'^\d+$', cell_text):
                                        grade_found = int(cell_text)
                                        break
                                
                                if grade_found:
                                    course_gpa = calculate_gpa_for_grade(grade_found, course_name)
                                    cycle_courses.append({
                                        'course_name': course_name,
                                        'grade': grade_found,
                                        'gpa': round(course_gpa, 2)
                                    })
                        
                        # Calculate average GPA for this cycle
                        if cycle_courses:
                            cycle_avg = sum(c['gpa'] for c in cycle_courses) / len(cycle_courses)
                            past_cycle_gpas.append(cycle_avg)
                            past_cycles_detail.append({
                                'cycle_name': cycle_name,
                                'courses': cycle_courses,
                                'average_gpa': round(cycle_avg, 2)
                            })
        except Exception as e:
            print(f"Error fetching past cycles: {str(e)}")
            # Continue with calculation even if past cycles fail
        
        # Combine all GPAs
        all_gpas = current_course_gpas + past_cycle_gpas
        cumulative_gpa = round(sum(all_gpas) / len(all_gpas), 2) if all_gpas else 0
        
        return jsonify({
            'cumulative_gpa': cumulative_gpa,
            'current_courses_count': len(current_course_gpas),
            'past_cycles_count': len(past_cycle_gpas),
            'past_cycle_gpas': [round(gpa, 2) for gpa in past_cycle_gpas],
            'past_cycles_detail': past_cycles_detail,
            'all_unique_courses': sorted(list(all_unique_courses))
        })
    except Exception as e:
        print(f"GPA calculation error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/api/assignments/<course_id>', methods=['GET'])
def assignments(course_id):
    session_id = request.headers.get('X-Session-ID')
    
    if not validate_session(session_id):
        return jsonify({'error': 'Session expired or invalid. Please log in again.'}), 401
    
    sess = user_sessions[session_id]
    
    try:
        assignments_data = get_assignments_for_class(sess, course_id)
        return jsonify({'assignments': assignments_data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/report-card', methods=['GET'])
def report_card():
    session_id = request.headers.get('X-Session-ID')
    
    if not validate_session(session_id):
        return jsonify({'error': 'Session expired or invalid. Please log in again.'}), 401
    
    sess = user_sessions[session_id]
    
    try:
        grades_url = f"{BASE_URL}/HomeAccess/Content/Student/ReportCards.aspx"
        grades_response = sess.get(grades_url)
        soup = BeautifulSoup(grades_response.text, 'html.parser')
        
        # Check if we are on the latest report card run
        dropdown = soup.find('select', id='plnMain_ddlRCRuns')
        if dropdown:
            options = dropdown.find_all('option')
            if options:
                last_option = options[-1]
                last_value = last_option.get('value')
                
                selected_option = dropdown.find('option', selected=True)
                current_value = selected_option.get('value') if selected_option else None
                
                # If we are not on the latest run, fetch it
                if current_value != last_value:
                    print(f"Switching to latest report card run: {last_value}")
                    parts = last_value.split('-')
                    rcrun = parts[0] if len(parts) >= 2 else last_value
                    
                    grades_response = sess.get(f"{grades_url}?RCRun={rcrun}")
                    soup = BeautifulSoup(grades_response.text, 'html.parser')

        report_card_table = soup.find('table', id='plnMain_dgReportCard')
        
        if not report_card_table:
            return jsonify({'cycles': [], 'overall_gpa': 0})

        # Find headers to map columns
        header_row = report_card_table.find('tr', class_='sg-asp-table-header-row')
        if not header_row:
            header_row = report_card_table.find('tr')
        
        headers = [th.get_text(strip=True) for th in header_row.find_all(['th', 'td'])]
        
        # Map cycle names (C1, C2, etc.) to column indices
        cycle_indices = {}
        for idx, header in enumerate(headers):
            if re.match(r'^C\d+$', header):
                cycle_indices[header] = idx
        
        print(f"Found cycle columns: {cycle_indices}")
        
        cycles_data = {c: [] for c in cycle_indices.keys()}
        
        rows = report_card_table.find_all('tr', class_='sg-asp-table-data-row')
        
        for row in rows:
            cells = row.find_all('td')
            if len(cells) < 2: continue
            
            course_code = cells[0].get_text(strip=True)
            course_link = cells[1].find('a')
            course_name = course_link.get_text(strip=True) if course_link else cells[1].get_text(strip=True)
            
            for cycle_name, idx in cycle_indices.items():
                if idx < len(cells):
                    grade_text = cells[idx].get_text(strip=True)
                    if grade_text and re.match(r'^\d+$', grade_text):
                        grade = int(grade_text)
                        gpa = round(calculate_gpa_for_grade(grade, course_name), 2)
                        
                        cycles_data[cycle_name].append({
                            'course': course_name,
                            'course_code': course_code,
                            'grade': grade,
                            'numeric_grade': grade,
                            'gpa': gpa
                        })

        all_cycles = []
        # Sort cycles by number (C1, C2...)
        sorted_cycles = sorted(cycles_data.keys(), key=lambda x: int(x[1:]))
        
        for cycle_key in sorted_cycles:
            courses = cycles_data[cycle_key]
            if courses:
                total_gpa = sum(c['gpa'] for c in courses)
                avg_gpa = round(total_gpa / len(courses), 2)
                
                all_cycles.append({
                    'cycle_name': f"Cycle {cycle_key[1:]}",
                    'courses': courses,
                    'average_gpa': avg_gpa
                })
        
        overall_gpa = 0
        total_courses = 0
        for cycle in all_cycles:
            for course in cycle['courses']:
                if course['gpa']:
                    overall_gpa += course['gpa']
                    total_courses += 1
        
        overall_avg_gpa = round(overall_gpa / total_courses, 2) if total_courses > 0 else 0
        
        return jsonify({
            'cycles': all_cycles,
            'overall_gpa': overall_avg_gpa
        })

    except Exception as e:
        print(f"Report card error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(port=5003, debug=True)