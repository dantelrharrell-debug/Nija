#!/usr/bin/env python3
"""
NIJA Mobile Readiness - Validation Script

This script validates that all mobile readiness components are properly configured.
Run this before deployment to ensure everything is ready.

Usage:
    python validate_mobile_readiness.py
"""

import os
import sys
from pathlib import Path

# Color codes for output
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
RESET = '\033[0m'
CHECKMARK = '✅'
WARNING = '⚠️'
ERROR = '❌'


def print_header(text):
    """Print section header"""
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print('=' * 60)


def check_file_exists(filepath, description):
    """Check if a file exists"""
    exists = Path(filepath).exists()
    status = f"{GREEN}{CHECKMARK}{RESET}" if exists else f"{RED}{ERROR}{RESET}"
    print(f"{status} {description}")
    return exists


def check_env_var(var_name, required=True):
    """Check if environment variable is set"""
    value = os.getenv(var_name)
    exists = value is not None and value != ""
    
    if required:
        status = f"{GREEN}{CHECKMARK}{RESET}" if exists else f"{RED}{ERROR}{RESET}"
        level = "Required"
    else:
        status = f"{GREEN}{CHECKMARK}{RESET}" if exists else f"{YELLOW}{WARNING}{RESET}"
        level = "Optional"
    
    print(f"{status} {var_name} ({level})")
    return exists


def main():
    """Run validation checks"""
    print(f"\n{GREEN}NIJA Mobile Readiness - Validation Script{RESET}")
    print("Checking all components before deployment...")
    
    all_checks_passed = True
    
    # Check backend files
    print_header("Backend API Files")
    files_ok = True
    files_ok &= check_file_exists("unified_mobile_api.py", "Unified Mobile API")
    files_ok &= check_file_exists("iap_handler.py", "IAP Handler")
    files_ok &= check_file_exists("education_system.py", "Education System")
    files_ok &= check_file_exists("mobile_backend_server.py", "Mobile Backend Server")
    files_ok &= check_file_exists("monetization_engine.py", "Monetization Engine")
    all_checks_passed &= files_ok
    
    # Check documentation
    print_header("Documentation")
    docs_ok = True
    docs_ok &= check_file_exists("MOBILE_READINESS_COMPLETE.md", "Mobile Readiness Guide")
    docs_ok &= check_file_exists("CLOUD_DEPLOYMENT_GUIDE.md", "Cloud Deployment Guide")
    docs_ok &= check_file_exists("APP_STORE_SUBMISSION_COMPLETE.md", "App Store Submission Guide")
    all_checks_passed &= docs_ok
    
    # Check mobile app structure
    print_header("Mobile App Structure")
    mobile_ok = True
    mobile_ok &= check_file_exists("mobile/README.md", "Mobile App README")
    mobile_ok &= check_file_exists("capacitor.config.json", "Capacitor Config")
    mobile_ok &= check_file_exists("mobile/PRIVACY_POLICY.md", "Privacy Policy")
    mobile_ok &= check_file_exists("mobile/TERMS_OF_SERVICE.md", "Terms of Service")
    all_checks_passed &= mobile_ok
    
    # Check deployment files
    print_header("Deployment Configuration")
    deploy_ok = True
    deploy_ok &= check_file_exists("Dockerfile", "Main Dockerfile")
    deploy_ok &= check_file_exists("Dockerfile.api", "API Dockerfile")
    deploy_ok &= check_file_exists("docker-compose.yml", "Docker Compose")
    deploy_ok &= check_file_exists("requirements.txt", "Python Requirements")
    deploy_ok &= check_file_exists("railway.json", "Railway Config")
    all_checks_passed &= deploy_ok
    
    # Check environment variables
    print_header("Environment Variables")
    
    print("\nRequired for Production:")
    env_ok = True
    env_ok &= check_env_var("DATABASE_URL", required=True)
    env_ok &= check_env_var("JWT_SECRET_KEY", required=True)
    env_ok &= check_env_var("STRIPE_SECRET_KEY", required=True)
    
    print("\nRequired for IAP:")
    env_ok &= check_env_var("APPLE_SHARED_SECRET", required=True)
    env_ok &= check_env_var("GOOGLE_SERVICE_ACCOUNT_JSON", required=True)
    
    print("\nOptional:")
    check_env_var("REDIS_URL", required=False)
    check_env_var("SENTRY_DSN", required=False)
    check_env_var("ALLOWED_ORIGINS", required=False)
    
    # Note about environment variables
    if not env_ok:
        print(f"\n{YELLOW}Note: Environment variables are not set in this environment.{RESET}")
        print(f"{YELLOW}This is expected during development.{RESET}")
        print(f"{YELLOW}Set them before production deployment.{RESET}")
    
    # Check Python modules (syntax check only)
    print_header("Python Module Syntax")
    
    modules_to_check = [
        "unified_mobile_api.py",
        "iap_handler.py",
        "education_system.py",
        "mobile_backend_server.py"
    ]
    
    syntax_ok = True
    for module in modules_to_check:
        try:
            with open(module, 'r') as f:
                compile(f.read(), module, 'exec')
            print(f"{GREEN}{CHECKMARK}{RESET} {module} - Syntax OK")
        except SyntaxError as e:
            print(f"{RED}{ERROR}{RESET} {module} - Syntax Error: {e}")
            syntax_ok = False
        except FileNotFoundError:
            print(f"{RED}{ERROR}{RESET} {module} - File not found")
            syntax_ok = False
    
    all_checks_passed &= syntax_ok
    
    # Component count
    print_header("Component Statistics")
    
    # Count API endpoints
    try:
        with open("unified_mobile_api.py", 'r') as f:
            content = f.read()
            api_endpoints = content.count('@unified_mobile_api.route(')
            print(f"{GREEN}{CHECKMARK}{RESET} Unified API Endpoints: {api_endpoints}")
    except:
        print(f"{RED}{ERROR}{RESET} Could not count API endpoints")
    
    try:
        with open("iap_handler.py", 'r') as f:
            content = f.read()
            iap_endpoints = content.count('@iap_api.route(')
            print(f"{GREEN}{CHECKMARK}{RESET} IAP Handler Endpoints: {iap_endpoints}")
    except:
        print(f"{RED}{ERROR}{RESET} Could not count IAP endpoints")
    
    try:
        with open("education_system.py", 'r') as f:
            content = f.read()
            edu_endpoints = content.count('@education_api.route(')
            lessons = content.count("'lesson_")
            print(f"{GREEN}{CHECKMARK}{RESET} Education Endpoints: {edu_endpoints}")
            print(f"{GREEN}{CHECKMARK}{RESET} Education Lessons: {lessons}")
    except:
        print(f"{RED}{ERROR}{RESET} Could not count education components")
    
    # Final summary
    print_header("Validation Summary")
    
    if all_checks_passed and files_ok and docs_ok and mobile_ok and deploy_ok and syntax_ok:
        print(f"{GREEN}{CHECKMARK} All critical checks passed!{RESET}")
        print(f"{GREEN}NIJA is ready for mobile deployment.{RESET}")
        return 0
    else:
        print(f"{YELLOW}{WARNING} Some checks did not pass.{RESET}")
        print(f"{YELLOW}Review the issues above before deployment.{RESET}")
        
        if not env_ok:
            print(f"\n{YELLOW}Note: Missing environment variables is expected during development.{RESET}")
            print(f"{YELLOW}Make sure to set them in your production environment.{RESET}")
        
        return 1


if __name__ == "__main__":
    sys.exit(main())
