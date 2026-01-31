"""
NIJA Mobile App - Lesson Graduation and Scoring System

Manages user progress through educational lessons, tracks scores,
and determines graduation/completion requirements.

Author: NIJA Trading Systems
Version: 1.0
Date: January 31, 2026
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from datetime import datetime
from enum import Enum

from mobile.lesson_map import (
    Lesson, LessonCategory, create_lesson_map,
    get_required_lessons, get_next_available_lesson
)


class GraduationTier(Enum):
    """Graduation tiers representing user proficiency levels"""
    NONE = "none"
    BEGINNER = "beginner"  # Completed Getting Started
    INTERMEDIATE = "intermediate"  # Completed Getting Started + Trading Basics
    ADVANCED = "advanced"  # Completed most lessons including Risk Management
    EXPERT = "expert"  # Completed all lessons
    CERTIFIED = "certified"  # Completed all + passed final assessment


@dataclass
class LessonAttempt:
    """Record of a single lesson attempt"""
    lesson_id: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    quiz_score: int = 0
    max_quiz_score: int = 0
    time_spent_seconds: int = 0
    passed: bool = False


@dataclass
class LessonProgress:
    """User's progress on a specific lesson"""
    lesson_id: str
    status: str  # 'not_started', 'in_progress', 'completed', 'mastered'
    attempts: List[LessonAttempt] = field(default_factory=list)
    best_score: int = 0
    total_time_spent: int = 0
    completed_at: Optional[datetime] = None
    mastered_at: Optional[datetime] = None
    
    def get_pass_rate(self) -> float:
        """Calculate pass rate across all attempts"""
        if not self.attempts:
            return 0.0
        passed = sum(1 for attempt in self.attempts if attempt.passed)
        return passed / len(self.attempts) * 100


@dataclass
class UserGraduationStatus:
    """Overall graduation status for a user"""
    user_id: str
    current_tier: GraduationTier = GraduationTier.NONE
    lesson_progress: Dict[str, LessonProgress] = field(default_factory=dict)
    total_points: int = 0
    achievements: List[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.now)
    last_lesson_at: Optional[datetime] = None
    graduated_at: Optional[datetime] = None
    
    def get_completion_percentage(self) -> float:
        """Calculate overall completion percentage"""
        all_lessons = create_lesson_map()
        if not all_lessons:
            return 0.0
        
        completed = sum(
            1 for lesson in all_lessons
            if self.lesson_progress.get(lesson.lesson_id, LessonProgress(lesson.lesson_id, 'not_started')).status == 'completed'
        )
        return completed / len(all_lessons) * 100
    
    def get_total_time_spent_hours(self) -> float:
        """Get total time spent on lessons in hours"""
        total_seconds = sum(
            progress.total_time_spent
            for progress in self.lesson_progress.values()
        )
        return total_seconds / 3600


# Graduation Requirements Configuration
GRADUATION_REQUIREMENTS = {
    GraduationTier.BEGINNER: {
        "required_lessons": ["gs_001", "gs_002", "gs_003", "gs_004", "gs_005", "gs_006", "gs_007", "gs_008"],
        "minimum_score": 70,  # 70% minimum on quizzes
        "required_categories": [LessonCategory.GETTING_STARTED],
        "minimum_points": 100,
        "description": "Complete all Getting Started lessons",
    },
    GraduationTier.INTERMEDIATE: {
        "required_lessons": [
            "gs_001", "gs_002", "gs_003", "gs_004", "gs_005", "gs_006", "gs_007", "gs_008",
            "tb_001", "tb_002",
        ],
        "minimum_score": 75,
        "required_categories": [LessonCategory.GETTING_STARTED, LessonCategory.TRADING_BASICS],
        "minimum_points": 300,
        "description": "Complete Getting Started and Trading Basics",
    },
    GraduationTier.ADVANCED: {
        "required_lessons": None,  # All required lessons must be completed
        "minimum_score": 80,
        "required_categories": [
            LessonCategory.GETTING_STARTED,
            LessonCategory.TRADING_BASICS,
            LessonCategory.RISK_MANAGEMENT,
        ],
        "minimum_points": 600,
        "description": "Complete all core educational content",
    },
    GraduationTier.EXPERT: {
        "required_lessons": None,  # All lessons
        "minimum_score": 85,
        "required_categories": None,  # All categories
        "minimum_points": 1000,
        "description": "Complete all lessons with high scores",
    },
    GraduationTier.CERTIFIED: {
        "required_lessons": None,  # All lessons
        "minimum_score": 90,
        "required_categories": None,  # All categories
        "minimum_points": 1200,
        "additional_requirements": ["final_assessment"],
        "description": "Complete all lessons and pass final certification exam",
    },
}


# Achievement definitions
ACHIEVEMENTS = {
    "first_lesson": {
        "name": "First Steps",
        "description": "Complete your first lesson",
        "points": 10,
    },
    "perfect_score": {
        "name": "Perfect Score",
        "description": "Score 100% on a quiz",
        "points": 25,
    },
    "speed_learner": {
        "name": "Speed Learner",
        "description": "Complete a lesson in under 2 minutes",
        "points": 15,
    },
    "dedicated_student": {
        "name": "Dedicated Student",
        "description": "Complete 5 lessons in one day",
        "points": 50,
    },
    "risk_aware": {
        "name": "Risk Management Master",
        "description": "Complete all Risk Management lessons",
        "points": 100,
    },
    "category_complete": {
        "name": "Category Master",
        "description": "Complete all lessons in a category",
        "points": 75,
    },
    "streak_7": {
        "name": "Week Warrior",
        "description": "Complete at least one lesson for 7 days straight",
        "points": 100,
    },
    "all_quizzes": {
        "name": "Quiz Champion",
        "description": "Pass all quizzes with 80%+ score",
        "points": 150,
    },
}


class GraduationManager:
    """Manages lesson graduation and scoring for users"""
    
    def __init__(self):
        self.user_statuses: Dict[str, UserGraduationStatus] = {}
    
    def get_or_create_status(self, user_id: str) -> UserGraduationStatus:
        """Get or create graduation status for a user"""
        if user_id not in self.user_statuses:
            self.user_statuses[user_id] = UserGraduationStatus(user_id=user_id)
        return self.user_statuses[user_id]
    
    def start_lesson(self, user_id: str, lesson_id: str) -> LessonAttempt:
        """Record that a user started a lesson"""
        status = self.get_or_create_status(user_id)
        
        # Get or create progress for this lesson
        if lesson_id not in status.lesson_progress:
            status.lesson_progress[lesson_id] = LessonProgress(
                lesson_id=lesson_id,
                status='in_progress'
            )
        else:
            status.lesson_progress[lesson_id].status = 'in_progress'
        
        # Create new attempt
        attempt = LessonAttempt(
            lesson_id=lesson_id,
            started_at=datetime.now()
        )
        status.lesson_progress[lesson_id].attempts.append(attempt)
        
        return attempt
    
    def complete_lesson(
        self,
        user_id: str,
        lesson_id: str,
        quiz_score: int,
        max_quiz_score: int,
        time_spent_seconds: int
    ) -> tuple[bool, str, List[str]]:
        """
        Mark a lesson as completed and calculate results
        
        Returns:
            Tuple of (passed: bool, message: str, new_achievements: List[str])
        """
        status = self.get_or_create_status(user_id)
        
        if lesson_id not in status.lesson_progress:
            return False, "Lesson not started", []
        
        progress = status.lesson_progress[lesson_id]
        
        if not progress.attempts:
            return False, "No active attempt found", []
        
        # Get the most recent attempt
        attempt = progress.attempts[-1]
        
        # Calculate pass/fail (70% minimum to pass)
        passing_score = max_quiz_score * 0.70
        passed = quiz_score >= passing_score
        
        # Update attempt
        attempt.completed_at = datetime.now()
        attempt.quiz_score = quiz_score
        attempt.max_quiz_score = max_quiz_score
        attempt.time_spent_seconds = time_spent_seconds
        attempt.passed = passed
        
        # Update progress
        progress.total_time_spent += time_spent_seconds
        
        if passed:
            progress.status = 'completed'
            progress.completed_at = datetime.now()
            
            # Update best score
            if quiz_score > progress.best_score:
                progress.best_score = quiz_score
            
            # Award points
            status.total_points += quiz_score
            status.last_lesson_at = datetime.now()
        
        # Check for achievements
        new_achievements = self._check_achievements(user_id, lesson_id, attempt, progress)
        
        # Update tier
        self._update_tier(user_id)
        
        # Build result message
        percentage = (quiz_score / max_quiz_score * 100) if max_quiz_score > 0 else 0
        if passed:
            message = f"✅ Lesson completed! Score: {percentage:.0f}% ({quiz_score}/{max_quiz_score} points)"
        else:
            message = f"❌ Not passed. Score: {percentage:.0f}% (need 70%+). Try again!"
        
        return passed, message, new_achievements
    
    def _check_achievements(
        self,
        user_id: str,
        lesson_id: str,
        attempt: LessonAttempt,
        progress: LessonProgress
    ) -> List[str]:
        """Check and award any new achievements"""
        status = self.user_statuses[user_id]
        new_achievements = []
        
        # First lesson
        if "first_lesson" not in status.achievements:
            if any(p.status == 'completed' for p in status.lesson_progress.values()):
                status.achievements.append("first_lesson")
                status.total_points += ACHIEVEMENTS["first_lesson"]["points"]
                new_achievements.append("first_lesson")
        
        # Perfect score
        if "perfect_score" not in status.achievements:
            if attempt.quiz_score == attempt.max_quiz_score and attempt.max_quiz_score > 0:
                status.achievements.append("perfect_score")
                status.total_points += ACHIEVEMENTS["perfect_score"]["points"]
                new_achievements.append("perfect_score")
        
        # Speed learner
        if "speed_learner" not in status.achievements:
            if attempt.time_spent_seconds < 120:  # Under 2 minutes
                status.achievements.append("speed_learner")
                status.total_points += ACHIEVEMENTS["speed_learner"]["points"]
                new_achievements.append("speed_learner")
        
        # Category completion
        lesson = next((l for l in create_lesson_map() if l.lesson_id == lesson_id), None)
        if lesson:
            category_lessons = [l for l in create_lesson_map() if l.category == lesson.category]
            category_completed = all(
                status.lesson_progress.get(l.lesson_id, LessonProgress(l.lesson_id, 'not_started')).status == 'completed'
                for l in category_lessons
            )
            
            achievement_key = f"category_{lesson.category.value}"
            if category_completed and achievement_key not in status.achievements:
                status.achievements.append(achievement_key)
                status.total_points += ACHIEVEMENTS["category_complete"]["points"]
                new_achievements.append(achievement_key)
        
        # Risk management master
        if "risk_aware" not in status.achievements:
            risk_lessons = [l for l in create_lesson_map() if l.category == LessonCategory.RISK_MANAGEMENT]
            all_risk_complete = all(
                status.lesson_progress.get(l.lesson_id, LessonProgress(l.lesson_id, 'not_started')).status == 'completed'
                for l in risk_lessons
            )
            if all_risk_complete:
                status.achievements.append("risk_aware")
                status.total_points += ACHIEVEMENTS["risk_aware"]["points"]
                new_achievements.append("risk_aware")
        
        return new_achievements
    
    def _update_tier(self, user_id: str):
        """Update user's graduation tier based on progress"""
        status = self.user_statuses[user_id]
        
        # Check each tier from highest to lowest
        for tier in [GraduationTier.CERTIFIED, GraduationTier.EXPERT,
                    GraduationTier.ADVANCED, GraduationTier.INTERMEDIATE,
                    GraduationTier.BEGINNER]:
            
            if self._meets_tier_requirements(user_id, tier):
                if status.current_tier != tier:
                    status.current_tier = tier
                    if tier == GraduationTier.CERTIFIED:
                        status.graduated_at = datetime.now()
                break
    
    def _meets_tier_requirements(self, user_id: str, tier: GraduationTier) -> bool:
        """Check if user meets requirements for a specific tier"""
        if tier == GraduationTier.NONE:
            return True
        
        status = self.user_statuses[user_id]
        requirements = GRADUATION_REQUIREMENTS[tier]
        
        # Check minimum points
        if status.total_points < requirements["minimum_points"]:
            return False
        
        # Check required lessons
        if requirements["required_lessons"]:
            for lesson_id in requirements["required_lessons"]:
                progress = status.lesson_progress.get(lesson_id)
                if not progress or progress.status != 'completed':
                    return False
                
                # Check minimum score
                if progress.best_score == 0:
                    continue  # No quiz
                
                # Get lesson to check max score
                lesson = next((l for l in create_lesson_map() if l.lesson_id == lesson_id), None)
                if lesson and lesson.quiz_questions:
                    max_score = sum(q.points for q in lesson.quiz_questions)
                    percentage = (progress.best_score / max_score * 100) if max_score > 0 else 100
                    if percentage < requirements["minimum_score"]:
                        return False
        
        # Check required categories
        if requirements.get("required_categories"):
            for category in requirements["required_categories"]:
                category_lessons = [l for l in create_lesson_map() if l.category == category]
                for lesson in category_lessons:
                    progress = status.lesson_progress.get(lesson.lesson_id)
                    if not progress or progress.status != 'completed':
                        return False
        
        # Check if all required lessons are completed (for higher tiers)
        if requirements["required_lessons"] is None:
            required_lessons = get_required_lessons()
            for lesson in required_lessons:
                progress = status.lesson_progress.get(lesson.lesson_id)
                if not progress or progress.status != 'completed':
                    return False
        
        return True
    
    def get_next_lesson_recommendation(self, user_id: str) -> Optional[Lesson]:
        """Get the next recommended lesson for the user"""
        status = self.get_or_create_status(user_id)
        
        completed_ids = [
            lesson_id for lesson_id, progress in status.lesson_progress.items()
            if progress.status == 'completed'
        ]
        
        return get_next_available_lesson(completed_ids)
    
    def get_progress_report(self, user_id: str) -> Dict:
        """Generate a comprehensive progress report for the user"""
        status = self.get_or_create_status(user_id)
        all_lessons = create_lesson_map()
        
        completed_count = sum(
            1 for p in status.lesson_progress.values()
            if p.status == 'completed'
        )
        
        # Calculate category progress
        category_progress = {}
        for category in LessonCategory:
            category_lessons = [l for l in all_lessons if l.category == category]
            if not category_lessons:
                continue
            
            completed_in_category = sum(
                1 for l in category_lessons
                if status.lesson_progress.get(l.lesson_id, LessonProgress(l.lesson_id, 'not_started')).status == 'completed'
            )
            
            category_progress[category.value] = {
                "completed": completed_in_category,
                "total": len(category_lessons),
                "percentage": (completed_in_category / len(category_lessons) * 100) if category_lessons else 0
            }
        
        # Next tier requirements
        next_tier = None
        for tier in [GraduationTier.BEGINNER, GraduationTier.INTERMEDIATE,
                    GraduationTier.ADVANCED, GraduationTier.EXPERT,
                    GraduationTier.CERTIFIED]:
            if tier.value != status.current_tier.value:
                if not self._meets_tier_requirements(user_id, tier):
                    next_tier = tier
                    break
        
        return {
            "user_id": user_id,
            "current_tier": status.current_tier.value,
            "next_tier": next_tier.value if next_tier else None,
            "total_points": status.total_points,
            "lessons_completed": completed_count,
            "lessons_total": len(all_lessons),
            "completion_percentage": status.get_completion_percentage(),
            "time_spent_hours": status.get_total_time_spent_hours(),
            "achievements": status.achievements,
            "category_progress": category_progress,
            "started_at": status.started_at.isoformat(),
            "last_lesson_at": status.last_lesson_at.isoformat() if status.last_lesson_at else None,
            "graduated_at": status.graduated_at.isoformat() if status.graduated_at else None,
        }
    
    def can_start_trading(self, user_id: str) -> tuple[bool, str]:
        """
        Determine if user has completed minimum required education to start trading
        
        Returns:
            Tuple of (allowed: bool, reason: str)
        """
        status = self.get_or_create_status(user_id)
        
        # Must complete at least Beginner tier
        if not self._meets_tier_requirements(user_id, GraduationTier.BEGINNER):
            return False, "Must complete Getting Started lessons before trading"
        
        # Must complete all compliance lessons
        compliance_lessons = [l for l in create_lesson_map() if l.category == LessonCategory.COMPLIANCE]
        for lesson in compliance_lessons:
            if lesson.is_required:
                progress = status.lesson_progress.get(lesson.lesson_id)
                if not progress or progress.status != 'completed':
                    return False, f"Must complete required lesson: {lesson.title}"
        
        # Must complete all required risk management lessons
        risk_lessons = [l for l in create_lesson_map() 
                       if l.category == LessonCategory.RISK_MANAGEMENT and l.is_required]
        for lesson in risk_lessons:
            progress = status.lesson_progress.get(lesson.lesson_id)
            if not progress or progress.status != 'completed':
                return False, f"Must complete required risk lesson: {lesson.title}"
        
        return True, "Ready to start trading"


# Global instance
_graduation_manager = None


def get_graduation_manager() -> GraduationManager:
    """Get the global graduation manager instance"""
    global _graduation_manager
    if _graduation_manager is None:
        _graduation_manager = GraduationManager()
    return _graduation_manager
