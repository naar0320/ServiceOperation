"""
Database Schema for Job Task Report System
Based on 3_JobEntry.py form fields
"""

import sqlite3
from pathlib import Path
from typing import Optional
from datetime import datetime

# Database schema definition - extracted from 3_JobEntry.py form
JOB_TASK_SCHEMA = {
    "job_tasks": {
        "columns": {
            # Auto-generated fields
            "job_id": {"type": "TEXT PRIMARY KEY", "description": "Auto-generated unique job ID"},
            "created_by": {"type": "TEXT NOT NULL", "description": "User ID who created the job entry"},
            "created_at": {"type": "TIMESTAMP NOT NULL", "description": "When the entry was created"},
            
            # Section 2: Job Type & Class
            "job_type": {"type": "TEXT NOT NULL", "description": "Job Type: Maintenance, Repair, or Inspection"},
            "job_class": {"type": "TEXT NOT NULL", "description": "Job Class: Electrical, Mechanical, Civil, or General"},
            
            # Section 2 & 3: Job Duration
            "date_start": {"type": "DATE NOT NULL", "description": "Job start date"},
            "time_start": {"type": "TIME NOT NULL", "description": "Job start time"},
            "date_end": {"type": "DATE", "description": "Job end date (optional)"},
            "time_end": {"type": "TIME", "description": "Job end time (optional)"},
            
            # Section 4: Personnel
            "technician": {"type": "TEXT NOT NULL", "description": "Assigned technician from registered users"},
            "verify_by": {"type": "TEXT", "description": "Name/ID of person who verifies the job (optional)"},
            
            # Section 5: Job Description
            "job_title": {"type": "TEXT NOT NULL", "description": "Brief job title (max 40 words)"},
            "job_details": {"type": "TEXT", "description": "Detailed job description (max 300 words)"},
            "remark": {"type": "TEXT", "description": "Additional remarks (max 100 words)"},
            
            # Section 6: Job Status
            "job_status": {"type": "TEXT NOT NULL", "description": "Status: Pending, Inprogress, or Completed"},
            
            # Section 8 & 9: Images
            "images_before_paths": {"type": "TEXT", "description": "CSV of 'before' image paths (minimum 4)"},
            "images_after_paths": {"type": "TEXT", "description": "CSV of 'after' image paths (minimum 4)"},
            
            # Metadata
            "last_modified": {"type": "TIMESTAMP", "description": "When the entry was last modified"},
            "last_modified_by": {"type": "TEXT", "description": "User ID of last modifier"},
        },
        "indexes": [
            "CREATE INDEX IF NOT EXISTS idx_job_id ON job_tasks(job_id)",
            "CREATE INDEX IF NOT EXISTS idx_created_at ON job_tasks(created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_job_status ON job_tasks(job_status)",
            "CREATE INDEX IF NOT EXISTS idx_technician ON job_tasks(technician)",
        ]
    },
    "spare_parts": {
        "columns": {
            "spare_id": {"type": "INTEGER PRIMARY KEY AUTOINCREMENT", "description": "Unique spare part ID"},
            "job_id": {"type": "TEXT NOT NULL", "description": "Reference to parent job_tasks.job_id"},
            "item_name": {"type": "TEXT NOT NULL", "description": "Name of spare part used"},
            "quantity": {"type": "INTEGER NOT NULL", "description": "Quantity of this item used"},
            "created_at": {"type": "TIMESTAMP NOT NULL", "description": "When spare part entry was created"},
        },
        "indexes": [
            "CREATE INDEX IF NOT EXISTS idx_spare_job_id ON spare_parts(job_id)",
        ]
    }
}


def init_database(db_path: Path) -> bool:
    """
    Initialize or update the database with the schema
    
    Args:
        db_path: Path to the SQLite database file
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Create job_tasks table
        job_tasks_cols = ", ".join([
            f"{col_name} {col_info['type']}"
            for col_name, col_info in JOB_TASK_SCHEMA["job_tasks"]["columns"].items()
        ])
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS job_tasks (
                {job_tasks_cols}
            )
        """)
        
        # Create spare_parts table with foreign key
        spare_parts_cols = ", ".join([
            f"{col_name} {col_info['type']}"
            for col_name, col_info in JOB_TASK_SCHEMA["spare_parts"]["columns"].items()
        ])
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS spare_parts (
                {spare_parts_cols},
                FOREIGN KEY (job_id) REFERENCES job_tasks(job_id) ON DELETE CASCADE
            )
        """)
        
        # Create all indexes
        for index_sql in JOB_TASK_SCHEMA["job_tasks"]["indexes"]:
            cursor.execute(index_sql)
        for index_sql in JOB_TASK_SCHEMA["spare_parts"]["indexes"]:
            cursor.execute(index_sql)
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error initializing database: {e}")
        return False


def validate_job_data(job_data: dict) -> tuple[bool, list]:
    """
    Validate job data before saving to database
    
    Args:
        job_data: Dictionary of job fields
        
    Returns:
        tuple: (is_valid, list of error messages)
    """
    errors = []
    
    # Required fields
    required_fields = [
        'job_id', 'created_by', 'created_at',
        'job_type', 'job_class',
        'date_start', 'time_start',
        'technician',
        'job_title', 'job_status'
    ]
    
    for field in required_fields:
        if field not in job_data or not job_data[field]:
            errors.append(f"Missing required field: {field}")
    
    # Validate job_type
    if job_data.get('job_type') not in ['', 'Maintenance', 'Repair', 'Inspection']:
        errors.append("Invalid job_type. Must be: Maintenance, Repair, or Inspection")
    
    # Validate job_class
    if job_data.get('job_class') not in ['', 'Electrical', 'Mechanical', 'Civil', 'General']:
        errors.append("Invalid job_class. Must be: Electrical, Mechanical, Civil, or General")
    
    # Validate job_status
    if job_data.get('job_status') not in ['', 'Pending', 'Inprogress', 'Completed']:
        errors.append("Invalid job_status. Must be: Pending, Inprogress, or Completed")
    
    # Validate word counts
    def count_words(text):
        return len(str(text).strip().split()) if text else 0
    
    if count_words(job_data.get('job_title', '')) > 40:
        errors.append("job_title exceeds 40 words")
    
    if count_words(job_data.get('job_details', '')) > 300:
        errors.append("job_details exceeds 300 words")
    
    if count_words(job_data.get('remark', '')) > 100:
        errors.append("remark exceeds 100 words")
    
    # Validate image counts
    before_images = job_data.get('images_before_paths', '').split(',') if job_data.get('images_before_paths') else []
    after_images = job_data.get('images_after_paths', '').split(',') if job_data.get('images_after_paths') else []
    
    before_count = len([img for img in before_images if img.strip()])
    after_count = len([img for img in after_images if img.strip()])
    
    if before_count < 4:
        errors.append(f"Need at least 4 'before' images, got {before_count}")
    
    if after_count < 4:
        errors.append(f"Need at least 4 'after' images, got {after_count}")
    
    return (len(errors) == 0, errors)


def get_database_summary() -> dict:
    """Get summary of database structure"""
    return {
        "tables": list(JOB_TASK_SCHEMA.keys()),
        "job_tasks_columns": len(JOB_TASK_SCHEMA["job_tasks"]["columns"]),
        "spare_parts_columns": len(JOB_TASK_SCHEMA["spare_parts"]["columns"]),
    }
