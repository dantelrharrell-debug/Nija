# NIJA Educational Onboarding System - Technical Specification

**Version:** 1.0  
**Date:** January 31, 2026  
**Status:** Ready for Implementation

---

## Executive Summary

This document provides the complete technical specification for implementing an educational onboarding system in the NIJA mobile trading app. The system will guide new users through 30-50 micro-lessons covering cryptocurrency trading basics, risk management, and platform features before allowing them to trade with real money.

### Division of Responsibilities

⚠️ **CRITICAL CLARIFICATION**:

- **Product Owner** (You): Design the full 30-50 lesson map structure, write all actual lesson content, create quiz questions and answers, write tutorial walkthroughs
- **Development Team**: Implement technical infrastructure (database, APIs, UI components, business logic, testing)

This spec provides the technical blueprint that developers will implement. Content is separated into JSON files that you (Product Owner) will populate with actual lessons, quizzes, and tutorial scripts.

---

## 1. System Overview

### 1.1 Architecture Diagram

```
Mobile App (React Native)
    ↓ REST API
Backend (Python/Flask)
    ↓ SQL
PostgreSQL Database
    ↑
Content Files (JSON - You create these)
```

### 1.2 Components

1. **Lesson Management**: CRUD for lessons, progress tracking
2. **Quiz System**: Multi-choice quizzes, scoring, explanations
3. **Graduation System**: Tier tracking, achievement awards
4. **Tutorial System**: Interactive walkthroughs with tooltips
5. **Compliance System**: Legal disclaimers, acknowledgments
6. **Trading Gate**: Blocks trading until requirements met

---

## 2. Data Models

### 2.1 Lesson

Product Owner defines content. Developers implement storage.

```typescript
interface Lesson {
  // IDs & Classification
  lesson_id: string;              // e.g., "gs_001"
  category: string;               // "getting_started", "trading_basics", etc.
  difficulty: "beginner" | "intermediate" | "advanced";
  order: number;                  // 1-50
  
  // Content (YOU WRITE THIS)
  title: string;
  content: string;                // Markdown supported
  key_points: string[];
  
  // Configuration
  duration_minutes: number;
  is_required: boolean;
  prerequisites: string[];        // Lesson IDs
  
  // Media (URLs you provide)
  image_url?: string;
  video_url?: string;
  
  // Compliance
  compliance_disclaimer?: "trading_risk" | "no_guarantee" | "not_advice" | "regulatory";
  
  // Quiz (YOU WRITE THESE)
  quiz_questions: QuizQuestion[];
}

interface QuizQuestion {
  question_id: string;
  question: string;               // YOU WRITE
  options: string[];              // 2-5 options, YOU WRITE
  correct_answer_index: number;   // 0-based, YOU SPECIFY
  explanation: string;            // Why answer is correct, YOU WRITE
  points: number;                 // Default: 10
}
```

### 2.2 Tutorial

```typescript
interface Tutorial {
  tutorial_id: string;
  name: string;                   // YOU WRITE
  description: string;            // YOU WRITE
  tutorial_type: "onboarding" | "feature_intro" | "workflow";
  
  steps: TutorialStep[];          // YOU WRITE THESE
}

interface TutorialStep {
  step_id: string;
  title: string;                  // YOU WRITE
  description: string;            // YOU WRITE
  target_element?: string;        // Element ID to highlight
  action_required: "tap" | "swipe" | "scroll" | "read";
}
```

---

## 3. Database Schema

Developers implement these tables:

```sql
-- Lessons (content from YOU)
CREATE TABLE lessons (
    lesson_id VARCHAR(50) PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    content TEXT NOT NULL,
    key_points JSONB,
    category VARCHAR(50),
    difficulty VARCHAR(20),
    duration_minutes INT,
    is_required BOOLEAN,
    prerequisites JSONB,
    "order" INT UNIQUE
);

-- Quiz questions (content from YOU)
CREATE TABLE quiz_questions (
    question_id VARCHAR(50) PRIMARY KEY,
    lesson_id VARCHAR(50) REFERENCES lessons(lesson_id),
    question TEXT,
    options JSONB,
    correct_answer_index INT,
    explanation TEXT,
    points INT DEFAULT 10
);

-- User progress (automatically tracked)
CREATE TABLE user_lesson_progress (
    user_id VARCHAR(50),
    lesson_id VARCHAR(50),
    status VARCHAR(20),
    best_score INT,
    completed_at TIMESTAMP,
    PRIMARY KEY (user_id, lesson_id)
);

-- Graduation status (automatically calculated)
CREATE TABLE user_graduation_status (
    user_id VARCHAR(50) PRIMARY KEY,
    current_tier VARCHAR(20),
    total_points INT,
    achievements JSONB,
    can_trade BOOLEAN
);
```

---

## 4. API Endpoints

Developers implement these endpoints:

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/lessons` | List all lessons |
| GET | `/lessons/{id}` | Get lesson details |
| POST | `/lessons/{id}/start` | Mark lesson started |
| POST | `/lessons/{id}/complete` | Submit quiz, get score |
| GET | `/user/graduation-status` | Get progress/tier |
| GET | `/tutorials` | List tutorials |
| POST | `/tutorials/{id}/start` | Start tutorial |
| POST | `/tutorials/{id}/complete-step` | Next step |
| POST | `/compliance/acknowledge` | Acknowledge disclaimer |

---

## 5. Content Structure (YOU CREATE THIS)

### 5.1 Directory Structure

```
content/
├── lessons/
│   ├── getting_started/
│   │   ├── gs_001.json      ← YOU CREATE
│   │   ├── gs_002.json      ← YOU CREATE
│   │   └── ...
│   ├── trading_basics/
│   ├── risk_management/
│   ├── platform_features/
│   ├── advanced_strategies/
│   └── compliance/
├── tutorials/
│   ├── onboard_welcome.json  ← YOU CREATE
│   └── ...
└── compliance/
    └── disclaimers.json      ← YOU CREATE
```

### 5.2 Lesson Content Template

**Copy this template for each lesson you create:**

```json
{
  "lesson_id": "gs_001",
  "title": "YOUR TITLE HERE",
  "category": "getting_started",
  "difficulty": "beginner",
  "lesson_type": "text",
  "duration_minutes": 3,
  "order": 1,
  "is_required": true,
  "prerequisites": [],
  
  "content": "# YOUR LESSON TITLE\n\nYOUR LESSON CONTENT HERE (Markdown format)...",
  
  "key_points": [
    "Key point 1 - YOU WRITE",
    "Key point 2 - YOU WRITE",
    "Key point 3 - YOU WRITE"
  ],
  
  "image_url": "https://cdn.nija.app/lessons/gs_001.jpg",
  "video_url": null,
  "compliance_disclaimer": "trading_risk",
  
  "quiz_questions": [
    {
      "question_id": "gs_001_q1",
      "question": "YOUR QUESTION HERE?",
      "options": [
        "Option A - WRONG",
        "Option B - CORRECT",
        "Option C - WRONG",
        "Option D - WRONG"
      ],
      "correct_answer_index": 1,
      "explanation": "EXPLAIN WHY B IS CORRECT",
      "points": 10,
      "order": 1
    }
  ]
}
```

### 5.3 Tutorial Template

```json
{
  "tutorial_id": "onboard_welcome",
  "name": "Welcome to NIJA",
  "description": "Quick intro to the app",
  "tutorial_type": "onboarding",
  "trigger": "on_first_launch",
  "is_required": true,
  
  "steps": [
    {
      "step_id": "welcome_1",
      "order": 1,
      "title": "Welcome!",
      "description": "👋 YOUR WELCOME MESSAGE HERE",
      "target_element": null,
      "overlay_position": "center",
      "action_required": "tap",
      "allow_skip": false
    },
    {
      "step_id": "welcome_2",
      "order": 2,
      "title": "Your Dashboard",
      "description": "YOUR DASHBOARD EXPLANATION HERE",
      "target_element": "dashboard_overview",
      "overlay_position": "bottom",
      "action_required": "read",
      "allow_skip": true
    }
  ]
}
```

---

## 6. Lesson Map Structure (YOU DESIGN THIS)

### 6.1 Categories

You need to create 30-50 lessons across these categories:

| Category | Suggested Count | Your Responsibility |
|----------|----------------|---------------------|
| getting_started | 8 | Design which topics, write content |
| trading_basics | 10 | Design which topics, write content |
| risk_management | 10 | Design which topics, write content |
| platform_features | 8 | Design which topics, write content |
| advanced_strategies | 6 | Design which topics, write content |
| compliance | 4 | Design which topics, write content |
| **TOTAL** | **46** | **YOU CREATE ALL** |

### 6.2 Example Lesson Map (YOU EXPAND THIS)

**Getting Started (8 lessons):**
- gs_001: Welcome to NIJA (YOU WRITE)
- gs_002: How Automated Trading Works (YOU WRITE)
- gs_003: Understanding Crypto Markets (YOU WRITE)
- gs_004: Exchange Connection Setup (YOU WRITE)
- gs_005: Your Trading Dashboard (YOU WRITE)
- gs_006: Trading Start Checklist (YOU WRITE)
- gs_007: How to Get Help (YOU WRITE)
- gs_008: Understanding Fees (YOU WRITE)

**Trading Basics (10 lessons) - YOU DESIGN:**
- tb_001: What is Technical Analysis? (YOU WRITE)
- tb_002: Understanding RSI (YOU WRITE)
- tb_003-010: (YOU DESIGN & WRITE)

**Risk Management (10 lessons) - YOU DESIGN:**
- rm_001: Never Risk More Than You Can Lose (YOU WRITE)
- rm_002: Position Sizing (YOU WRITE)
- rm_003-010: (YOU DESIGN & WRITE)

*Continue for all categories...*

---

## 7. Compliance Disclaimers (YOU WRITE THIS)

### 7.1 Required Disclaimers

You need to provide legal disclaimer text for:

```json
{
  "trading_risk": {
    "title": "Risk Disclosure",
    "content": "⚠️ YOUR LEGAL DISCLAIMER TEXT HERE about trading risks..."
  },
  "no_guarantee": {
    "title": "Performance Notice",
    "content": "📊 YOUR TEXT about past performance not guaranteeing results..."
  },
  "not_advice": {
    "title": "Not Financial Advice",
    "content": "💼 YOUR TEXT clarifying this is a tool, not advice..."
  },
  "regulatory": {
    "title": "Regulatory Notice",
    "content": "⚖️ YOUR TEXT about jurisdictional compliance..."
  }
}
```

---

## 8. Graduation System (DEVELOPERS IMPLEMENT)

### 8.1 Tier Requirements

Developers implement logic based on these rules:

| Tier | Requirements |
|------|--------------|
| Beginner | Complete all "getting_started" lessons, 70%+ score |
| Intermediate | + Complete "trading_basics", 75%+ score |
| Advanced | + Complete "risk_management", 80%+ score |
| Expert | Complete all lessons, 85%+ score |
| Certified | Complete all + acknowledge all compliance, 90%+ score |

### 8.2 Trading Eligibility

Users can trade when:
- ✅ Reached at least "Beginner" tier
- ✅ Completed specific required lessons (rm_001, rm_002, cp_001)
- ✅ Acknowledged all compliance disclosures

Developers implement gating logic.

---

## 9. Implementation Timeline

### Week 1: Backend Foundation
**Developers:**
- Create database schema
- Implement API endpoints
- Write business logic tests

### Week 1-2: Content Creation
**Product Owner (YOU):**
- ✍️ Design complete lesson map (30-50 lessons)
- ✍️ Write all lesson content (titles, content, key points)
- ✍️ Create all quiz questions (question, options, answers, explanations)
- ✍️ Write all tutorial scripts (step descriptions)
- ✍️ Write compliance disclaimer text

**Developers:**
- Create content import scripts
- Validate content format

### Week 2-3: Frontend UI
**Developers:**
- Build lesson viewer
- Build quiz engine
- Build progress dashboard
- Build tutorial overlay

### Week 3-4: Integration & Testing
**Developers:**
- Integrate all components
- E2E testing
- Bug fixes

### Week 4-5: Polish & Launch
- UI/UX refinement
- Performance optimization
- User acceptance testing
- Production deployment

---

## 10. Your Action Items (Product Owner)

### Immediate (Week 1):
- [ ] Review and approve this technical spec
- [ ] Design complete lesson map structure (which 30-50 lessons)
- [ ] Determine lesson order and prerequisites

### Content Creation (Week 1-2):
- [ ] Write lesson content for all 30-50 lessons
- [ ] Create 2-3 quiz questions per lesson (60-150 total questions)
- [ ] Write quiz answer explanations
- [ ] Design and write 8-12 tutorial walkthroughs
- [ ] Write compliance disclaimer text (4 disclosures)

### Review (Week 3):
- [ ] Review developer implementation
- [ ] Test lesson content in UI
- [ ] Verify quiz functionality
- [ ] Test tutorial flows

---

## 11. Content Quality Guidelines

When writing lesson content, ensure:

✅ **Educational Value:**
- Clear, concise explanations
- Real examples
- Avoid jargon (or explain it)

✅ **Engagement:**
- Conversational tone
- Short paragraphs
- Bullet points and emojis
- Realistic time estimates

✅ **Safety:**
- Emphasize risk management
- No guarantees of profit
- Disclaimer where appropriate

✅ **Quizzes:**
- Test actual understanding, not memorization
- Wrong answers should be plausible
- Explanations should teach

---

## 12. Sample Content (Your Reference)

### Good Lesson Example:

```markdown
# Understanding RSI

The RSI (Relative Strength Index) is like a speedometer for cryptocurrency price movements.

## What It Measures

RSI ranges from 0 to 100 and tells you if a coin is:
- **Below 30**: Oversold (may bounce up)
- **Above 70**: Overbought (may fall down)
- **Around 50**: Neutral

## Why NIJA Uses It

NIJA watches RSI to find good entry points. When RSI crosses above 30, it signals the price may be recovering from a dip.

⚠️ **Important**: RSI is just one indicator. NIJA combines it with other signals for better accuracy.
```

### Good Quiz Example:

```json
{
  "question": "What does RSI below 30 typically indicate?",
  "options": [
    "The price will definitely go up",
    "The asset may be oversold and could bounce",
    "The price will definitely go down",
    "Time to sell immediately"
  ],
  "correct_answer_index": 1,
  "explanation": "RSI below 30 suggests oversold conditions, which may lead to a bounce, but it's not guaranteed. That's why NIJA uses multiple indicators together."
}
```

---

## 13. Questions & Support

**For Developers:**
- Technical questions → Engineering lead
- API design questions → Backend team lead
- UI/UX questions → Design team lead

**For Product Owner:**
- Content format questions → Developers (use templates above)
- Business logic questions → Product manager
- Legal/compliance questions → Legal team

---

## Appendix: Content Checklist

### Lessons (30-50 total)
- [ ] Getting Started (8)
- [ ] Trading Basics (10)
- [ ] Risk Management (10)
- [ ] Platform Features (8)
- [ ] Advanced Strategies (6)
- [ ] Compliance (4)

### Quizzes
- [ ] 60-150 quiz questions (2-3 per lesson)
- [ ] All answers specified
- [ ] All explanations written

### Tutorials
- [ ] Welcome tutorial (5-7 steps)
- [ ] First trade setup (5-7 steps)
- [ ] Understanding positions (4-5 steps)
- [ ] Notification setup (3-4 steps)
- [ ] Performance analytics (4-5 steps)
- [ ] Risk adjustment (4-5 steps)
- [ ] Additional tutorials (2-4 more)

### Compliance
- [ ] Trading risk disclaimer
- [ ] No guarantee disclaimer
- [ ] Not financial advice disclaimer
- [ ] Regulatory notice

---

**END OF TECHNICAL SPECIFICATION**

**Summary:**
- **Developers**: Build the system (database, APIs, UI, logic)
- **Product Owner**: Create all content (lessons, quizzes, tutorials, disclaimers)

The two efforts proceed in parallel, merge in Week 3 for integration testing.
