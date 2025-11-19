import requests
from bs4 import BeautifulSoup
import getpass
import re

def get_grades():
    """
    Main function to get user's grades from Home Access Center using web scraping
    """
    print("=" * 50)
    print("Home Access Center - Grade Checker")
    print("=" * 50)
    print("\nIMPORTANT: Use your actual HAC login credentials")
    print("URL: https://lis-hac.eschoolplus.powerschool.com/")
    print("=" * 50)
    
    # Get user credentials
    username = input("\nEnter your HAC username: ").strip()
    password = getpass.getpass("Enter your HAC password: ")
    
    print("\nAttempting to log in...")
    
    # Create a session to maintain cookies
    session = requests.Session()
    
    # Base URL
    base_url = "https://lis-hac.eschoolplus.powerschool.com"
    login_url = f"{base_url}/HomeAccess/Account/LogOn"
    
    try:
        # First, get the login page to extract any required tokens
        print("Loading login page...")
        response = session.get(login_url)
        
        if response.status_code != 200:
            print(f"❌ Failed to load login page (Status: {response.status_code})")
            return
        
        # Parse the login page to get form details
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find the login form
        login_form = soup.find('form')
        
        # Prepare login data
        login_data = {
            'Database': '10',  # Default database value for eSchoolPLUS
            'LogOnDetails.UserName': username,
            'LogOnDetails.Password': password
        }
        
        # Look for any hidden inputs (like __RequestVerificationToken)
        if login_form:
            hidden_inputs = login_form.find_all('input', type='hidden')
            for hidden in hidden_inputs:
                name = hidden.get('name')
                value = hidden.get('value', '')
                if name:
                    login_data[name] = value
        
        # Attempt to log in
        print("Authenticating...")
        login_response = session.post(login_url, data=login_data, allow_redirects=True)
        
        # Check if login was successful
        if 'LogOn' in login_response.url or login_response.status_code == 401:
            print("\n❌ Authentication Failed")
            print("\nYour credentials were not accepted. Please check:")
            print("1. Username and password are correct")
            print("2. Account is not locked")
            print("3. Try logging in at the website directly first")
            return
        
        print("✓ Login successful!")
        print("\nFetching grades...")
        
        # Navigate to the grades page (ClassWork)
        grades_url = f"{base_url}/HomeAccess/Content/Student/Assignments.aspx"
        grades_response = session.get(grades_url)
        
        if grades_response.status_code != 200:
            # Try alternative grades URL
            grades_url = f"{base_url}/HomeAccess/Content/Student/Classes.aspx"
            grades_response = session.get(grades_url)
        
        # Parse the grades page
        soup = BeautifulSoup(grades_response.text, 'html.parser')
        
        # Extract grade information
        print("\n" + "=" * 50)
        print("Your Current Grades:")
        print("=" * 50)
        
        grades = []
        
        # Find all course containers
        classes = soup.find_all('div', class_='AssignmentClass')
        
        for cls in classes:
            # Get course name
            course_name_elem = cls.find('a', class_='sg-header-heading')
            if course_name_elem:
                course_name = course_name_elem.get_text(strip=True)
                
                # Look for average/grade in the header
                avg_elem = cls.find('span', class_='sg-header-heading sg-right')
                if avg_elem:
                    grade_text = avg_elem.get_text(strip=True)
                    # Remove "Cycle Average" prefix if present
                    grade_text = grade_text.replace('Cycle Average', '').strip()
                    
                    if grade_text:  # Only add if there's a grade
                        grades.append({'name': course_name, 'grade': grade_text})
        
        if grades:
            total = 0
            count = 0
            
            for course in grades:
                print(f"\n{course['name']}: {course['grade']}")
                
                # Try to extract numeric grade (remove % symbol if present)
                grade_text = course['grade'].replace('%', '').strip()
                grade_match = re.search(r'(\d+\.?\d*)', grade_text)
                if grade_match:
                    try:
                        numeric_grade = float(grade_match.group(1))
                        total += numeric_grade
                        count += 1
                    except ValueError:
                        pass
            
            # Display overall average
            if count > 0:
                overall_average = total / count
                print("\n" + "=" * 50)
                print(f"Overall Average: {overall_average:.2f}")
                print("=" * 50)
            else:
                print("\n⚠ Could not calculate numeric average")
        else:
            print("\n⚠ Could not find grades on the page.")
            print("\nThis could mean:")
            print("1. No grades have been posted yet")
            print("2. The page structure is different than expected")
            print("3. You need to access a different page")
            print("\nTry logging in manually at:")
            print("https://lis-hac.eschoolplus.powerschool.com/")
            
    except requests.exceptions.RequestException as e:
        print(f"\n❌ Network error occurred: {e}")
    except Exception as e:
        print(f"\n❌ An error occurred: {e}")
        print(f"Error details: {type(e).__name__}")

if __name__ == "__main__":
    get_grades()
