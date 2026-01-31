# NIJA Educational Curriculum

**Transform from Trading Bot to Financial Operating System**

> **"You're not building a bot anymore. You're building a financial operating system."**

This directory contains the complete educational curriculum for the NIJA Financial Operating System. The curriculum transforms users from complete beginners into certified traders through a structured, gamified learning experience.

---

## 📚 What's in This Directory

### Core Files

1. **`master_curriculum.json`**
   - Complete curriculum specification in JSON format
   - Includes all lesson metadata, tier definitions, learning paths
   - Single source of truth for the educational system
   - Used by backend API and mobile app

2. **`TIER_ALIGNMENT.md`**
   - Detailed tier progression documentation
   - Prerequisite chains and validation rules
   - Trading eligibility requirements
   - Implementation guidelines for developers

---

## 🎓 Curriculum Overview

### Current Status (v1.0.0)

- **Total Lessons:** 20 (expanding to 40+)
- **Categories:** 6
- **Graduation Tiers:** 5 (3 active, 2 planned)
- **Estimated Time:** 2 hours for current content
- **Quiz Questions:** 60+ with explanations

### Lesson Categories

| Category | Code | Lessons | Status | Description |
|----------|------|---------|--------|-------------|
| **Getting Started** | gs_ | 8 | ✅ Complete | Platform basics and setup |
| **Trading Basics** | tb_ | 10 | ✅ Complete | Technical analysis fundamentals |
| **Risk Management** | rm_ | 4 | ✅ Complete | Capital protection strategies |
| **Platform Features** | pf_ | 0 | 🚧 Planned | Dashboard and advanced features |
| **Advanced Strategies** | as_ | 0 | 🚧 Planned | Optimization techniques |
| **Compliance** | cp_ | 1 | ✅ Complete | Legal disclaimers |

---

## 🎯 Graduation Tier System

### Tier Progression

```
┌─────────┐     ┌──────────┐     ┌──────────────┐     ┌─────────┐     ┌───────────┐
│  None   │ --> │ Beginner │ --> │ Intermediate │ --> │ Advanced│ --> │  Expert   │
│   0     │     │    8     │     │     13       │     │   20    │     │    40     │
└─────────┘     └──────────┘     └──────────────┘     └─────────┘     └───────────┘
                     30min              1hr                 2hr              4hr
                                                                              │
                                                                              v
                                                                        ┌───────────┐
                                                                        │ Certified │
                                                                        │  40+exam  │
                                                                        └───────────┘
                                                                              5hr
```

### What Each Tier Unlocks

**Beginner (8 lessons, 30 min):**
- ✅ Platform dashboard access
- ✅ Paper trading mode
- ✅ API connection setup
- ⚠️ Limited live trading (with safety requirements)

**Intermediate (13 lessons, 1 hr):**
- ✅ Full live trading access
- ✅ Basic strategy customization
- ✅ Performance analytics
- ✅ Copy trading (follow others)

**Advanced (20 lessons, 2 hr):**
- ✅ Advanced strategy settings
- ✅ Multi-timeframe analysis
- ✅ Portfolio optimization
- ✅ Copy trading provider access

**Expert (40 lessons, 4 hr) - Future:**
- ✅ Custom strategy creation
- ✅ API access for integrations
- ✅ Priority support
- ✅ Beta features

**Certified (40 lessons + exam, 5 hr) - Future:**
- ✅ Certified trader badge
- ✅ Teaching/mentoring access
- ✅ Revenue sharing opportunities

---

## 🚨 Trading Eligibility Requirements

### Minimum Requirements to Enable Live Trading

Users **MUST** complete these lessons before live trading:

**Mandatory Lessons:**
1. ✅ gs_001 - Welcome to NIJA
2. ✅ gs_002 - How Automated Trading Works
3. ✅ gs_003 - Understanding Cryptocurrency Markets
4. ✅ gs_004 - Exchange Connection Setup
5. ✅ gs_006 - Trading Start Checklist
6. ✅ **rm_001** - Never Risk More Than You Can Lose ⚠️
7. ✅ **rm_002** - Position Sizing and Risk Per Trade ⚠️
8. ✅ **rm_003** - Stop-Loss Strategies ⚠️
9. ✅ **cp_001** - Risk Disclosure and Legal Notice ⚠️

**Additional Requirements:**
- Minimum quiz score: 70% on each lesson
- Acknowledge all compliance disclaimers
- Configure risk limits in account settings
- Exchange API keys connected

---

## 📖 Learning Paths

### 1. Essential Trading Path (0.75 hr)
**Minimum required to start trading safely**

Lessons: gs_001, gs_002, gs_003, gs_004, gs_005, gs_006, rm_001, rm_002, rm_003, cp_001

### 2. Beginner Trader Path (0.5 hr)
**Complete path for new traders**

Lessons: gs_001 through gs_008

### 3. Technical Analysis Mastery (1 hr)
**Deep dive into technical analysis**

Lessons: tb_001 through tb_010  
Prerequisite: Beginner tier

### 4. Risk Management Excellence (0.4 hr)
**Master risk control and capital protection**

Lessons: rm_001 through rm_004  
Prerequisite: Beginner tier

---

## 🏆 Achievement System

Users earn points and badges for completing lessons and reaching milestones:

### Achievements

- **First Steps** (10 pts) - Complete your first lesson
- **Perfect Score** (25 pts) - Score 100% on a quiz
- **Speed Learner** (15 pts) - Complete a lesson in under 2 minutes
- **Dedicated Student** (50 pts) - Complete 5 lessons in one day
- **Risk Management Master** (100 pts) - Complete all Risk Management lessons
- **Category Master** (75 pts) - Complete all lessons in a category
- **Week Warrior** (100 pts) - 7-day learning streak
- **Quiz Champion** (150 pts) - Pass all quizzes with 80%+

---

## 📊 Lesson Structure

Each lesson includes:

### Content
- **Title & Description:** Clear learning objectives
- **Duration:** Estimated completion time (2-7 minutes)
- **Key Points:** 3-5 main takeaways
- **Full Content:** Detailed lesson material (Markdown format)
- **Compliance Disclaimers:** Where applicable

### Assessment
- **Quiz Questions:** 2-3 multiple choice questions
- **Options:** 4 choices per question
- **Explanations:** Why the correct answer is right
- **Points:** 10 points per question

### Metadata
- **Lesson ID:** Unique identifier (e.g., gs_001)
- **Category:** Which category it belongs to
- **Order:** Sequence position
- **Difficulty:** Beginner, Intermediate, or Advanced
- **Prerequisites:** Required prior lessons
- **Required Flag:** Must complete before trading

---

## 🔐 Compliance and Safety

### Why Education is Mandatory

The curriculum serves critical purposes:

1. **Legal Protection:** Users understand risks before trading
2. **User Safety:** Prevents uninformed trading with real money
3. **Platform Integrity:** Reduces support burden
4. **Regulatory Compliance:** Demonstrates due diligence

### Enforcement

- Tier requirements are **mandatory**, not optional
- Users cannot skip tiers or bypass prerequisites
- Trading access is automatically gated by tier
- All risk management lessons are required

---

## 🔧 For Developers

### Implementing the Curriculum

**Backend:**
- Import `master_curriculum.json` into database
- Implement tier checking logic (see `mobile/lesson_graduation.py`)
- Create REST API endpoints (see `docs/LESSON_SYSTEM_TECHNICAL_SPEC.md`)
- Enforce prerequisite chains

**Frontend (Mobile App):**
- Display lessons by category
- Track user progress
- Show tier badges and progress bars
- Quiz engine with instant feedback
- Gamification elements (points, achievements)

**Key Files:**
- `mobile/lesson_map.py` - Lesson content and data structures
- `mobile/lesson_graduation.py` - Tier logic and scoring
- `curriculum/master_curriculum.json` - Centralized curriculum spec
- `curriculum/TIER_ALIGNMENT.md` - Detailed tier documentation

---

## 📈 Expansion Roadmap

### Phase 2: Expert Tier (Q2 2026)
- Add 8 Platform Features lessons
- Add 6 Advanced Strategies lessons
- Add 6 more Risk Management lessons
- Total: 40 lessons

### Phase 3: Certification (Q3 2026)
- Comprehensive final assessment exam
- Practical trading challenges
- Peer review system

### Phase 4: Specializations (Q4 2026)
- Day Trading Specialist track
- Swing Trading Specialist track
- Risk Manager Specialist track
- Technical Analyst Specialist track

---

## 📞 Support

### For Users
- General questions: support@nija.app
- Lesson issues: education@nija.app
- Quiz disputes: education@nija.app

### For Developers
- Technical questions: See `docs/LESSON_SYSTEM_TECHNICAL_SPEC.md`
- Implementation help: Review `mobile/lesson_graduation.py`
- API documentation: See technical spec

### For Content Creators
- Content guidelines: See `docs/CONTENT_CREATION_GUIDE.md`
- Lesson templates: See technical spec Section 5
- Example lessons: Review `mobile/lesson_map.py`

---

## 📝 Version History

### v1.0.0 (January 31, 2026)
- ✅ 20 lessons across 3 categories
- ✅ 60+ quiz questions with explanations
- ✅ 3 active graduation tiers (Beginner, Intermediate, Advanced)
- ✅ Trading eligibility gating system
- ✅ Achievement and points system
- ✅ Prerequisite validation
- ✅ Master curriculum JSON document
- ✅ Complete tier alignment documentation

---

## 🎯 Key Metrics

### Current Curriculum Stats

- **Lessons:** 20 complete, 20+ planned
- **Quiz Questions:** 60+
- **Total Points Available:** 400+
- **Categories:** 6 (3 active, 3 planned)
- **Learning Paths:** 4 defined paths
- **Estimated Time:** 2 hours (expanding to 5+)
- **Languages:** English (more planned)
- **Format:** Mobile-first, web-accessible

### User Journey Metrics (Target)

- **Time to Beginner:** 30 minutes
- **Time to Trading-Ready:** 45 minutes (essential path)
- **Time to Intermediate:** 1 hour
- **Time to Advanced:** 2 hours
- **Completion Rate Target:** 75%+
- **Average Quiz Score Target:** 85%+

---

## 🌟 Summary

The NIJA Educational Curriculum transforms the platform from a simple trading bot into a comprehensive **Financial Operating System**. Through structured, gamified learning:

✅ **Users learn safely** before risking capital  
✅ **Platform reduces liability** through documented education  
✅ **Compliance is built-in** with required disclaimers  
✅ **Engagement increases** through achievements and tiers  
✅ **Community grows** with certified traders teaching others

**This curriculum is the foundation for responsible, sustainable growth.**

---

**Version:** 1.0.0  
**Last Updated:** January 31, 2026  
**Maintained By:** NIJA Education Team  
**Status:** Production Ready
