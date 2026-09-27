import os
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import feedparser
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS

try:
    from google import genai
except ImportError:
    genai = None

app = Flask(__name__, template_folder='templates')
CORS(app)

# ==========================================
# MEMORY CACHE (15 MIN TTL)
# ==========================================
LEADS_CACHE = {}
CACHE_TIMEOUT = 900

def get_from_cache(skill, country, niche):
    cache_key = f"{skill.lower().strip()}_{country.lower().strip()}_{niche.lower().strip()}"
    if cache_key in LEADS_CACHE:
        cached_data, timestamp = LEADS_CACHE[cache_key]
        if time.time() - timestamp < CACHE_TIMEOUT:
            return cached_data
        else:
            del LEADS_CACHE[cache_key]
    return None

def save_to_cache(skill, country, niche, data):
    cache_key = f"{skill.lower().strip()}_{country.lower().strip()}_{niche.lower().strip()}"
    LEADS_CACHE[cache_key] = (data, time.time())

def clean_html(raw_html):
    if not raw_html:
        return ""
    cleanr = re.compile('<.*?>')
    return re.sub(cleanr, '', str(raw_html)).strip()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
ai_client = None
if GEMINI_API_KEY and genai:
    try:
        ai_client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print("Gemini init error:", e)

WEB_HEADERS = {
    'User-Agent': 'ClientHunterPro/4.0 (Mozilla/5.0 Windows NT 10.0; Win64; x64)'
}

# ==========================================
# 51 SKILLS MATRIX & MULTI-TAGS DATABASE
# ==========================================
SKILL_DATABASE = [
    {
        "id": "web_dev",
        "tags": ["web", "website", "wordpress", "elementor", "wix", "squarespace", "webflow"],
        "demo": "https://demo-web.agency-preview.com",
        "maps_no_site": "🔥 High Priority: Business lacks an official website. Direct lead for complete web design & development.",
        "maps_has_site": "⚠️ Web Upgrade Needed: Site found. Offer performance, SSL, or modern UI overhaul.",
        "fb_req": "📱 Facebook Business Lead: Requires website integration and conversion landing pages."
    },
    {
        "id": "frontend_dev",
        "tags": ["frontend", "react", "vue", "angular", "html", "css", "tailwind", "nextjs"],
        "demo": "https://demo-web.agency-preview.com",
        "maps_no_site": "🔥 Needs Web Front-End: Modern responsive web application setup required.",
        "maps_has_site": "⚠️ Frontend Redesign: Optimize page speed, UI responsiveness, and mobile UX.",
        "fb_req": "📱 Front-End Client: Requires web interface upgrade and interactive client portal."
    },
    {
        "id": "backend_dev",
        "tags": ["backend", "python", "flask", "django", "node", "php", "laravel", "api"],
        "demo": "https://demo-web.agency-preview.com",
        "maps_no_site": "🔥 Custom Software Needs: Requires backend API, database structure & server deployment.",
        "maps_has_site": "⚙️ Backend Optimization: Database tuning, API integration & server management opportunity.",
        "fb_req": "💻 Backend/API Integration requirement for client booking or internal workflow."
    },
    {
        "id": "ecommerce",
        "tags": ["ecommerce", "e-commerce", "shopify", "woocommerce", "magento", "online store"],
        "demo": "https://demo-store.agency-preview.com",
        "maps_no_site": "🛍️ E-Commerce Launch Opportunity: Business operates offline/socially; pitch Shopify or WooCommerce store.",
        "maps_has_site": "🛒 Store Optimization: Pitch payment gateway setup, upsell funnels, and checkout UX improvements.",
        "fb_req": "🛍️ E-Commerce Client: Needs online store creation and product catalogue setup."
    },
    {
        "id": "mobile_app",
        "tags": ["mobile app", "android", "ios", "flutter", "react native", "app development"],
        "demo": "https://demo-web.agency-preview.com",
        "maps_no_site": "📲 Mobile App Potential: Local business candidate for custom iOS/Android customer app.",
        "maps_has_site": "📱 Companion App: Opportunity to build mobile application linked to existing web system.",
        "fb_req": "📲 App Hiring Post: Client seeking mobile app developer for cross-platform app."
    },
    {
        "id": "ui_ux",
        "tags": ["ui/ux", "ui design", "ux design", "figma", "app design", "wireframe", "prototype"],
        "demo": "https://demo-branding.agency-preview.com",
        "maps_no_site": "🎨 Wireframing & UI Setup: Needs complete user experience design before web/app launch.",
        "maps_has_site": "🎨 UX Audit & Redesign: High drop-off risk; pitch user experience audit & Figma UI redesign.",
        "fb_req": "🎨 Visual UX Redesign: Seeking Figma designer for web or mobile application layout."
    },
    {
        "id": "cyber_security",
        "tags": ["cyber security", "ssl", "malware removal", "website security", "penetration testing"],
        "demo": "https://demo-web.agency-preview.com",
        "maps_no_site": "🔒 Security Setup: Critical need for secure infrastructure and data protection.",
        "maps_has_site": "🚨 Security Vulnerability: SSL or HTTP warnings detected. Pitch malware protection & security hardening.",
        "fb_req": "🔒 Security & Compliance Request: Looking for security audit and vulnerability testing."
    },
    {
        "id": "devops_cloud",
        "tags": ["devops", "aws", "cloud", "docker", "kubernetes", "server setup", "hosting"],
        "demo": "https://demo-web.agency-preview.com",
        "maps_no_site": "☁️ Cloud Migration: Opportunity to setup cloud server (AWS/GCP/DigitalOcean) for business.",
        "maps_has_site": "⚡ Cloud Optimization: Server downtime & latency fix opportunity.",
        "fb_req": "☁️ DevOps Requirement: Seeking server admin for Docker/AWS setup and CI/CD pipeline."
    },
    {
        "id": "game_dev",
        "tags": ["game dev", "unity", "unreal engine", "2d game", "3d game", "game design"],
        "demo": "https://demo-branding.agency-preview.com",
        "maps_no_site": "🎮 Gamification Potential: Opportunity to build promotional interactive web games.",
        "maps_has_site": "🎮 Interactive Experience: Pitch gamified web features to increase client retention.",
        "fb_req": "🎮 Game Hiring Requirement: Client seeking Unity/Unreal developer for gaming project."
    },
    {
        "id": "qa_testing",
        "tags": ["qa", "quality assurance", "software testing", "bug fixing", "automation testing"],
        "demo": "https://demo-web.agency-preview.com",
        "maps_no_site": "🧪 System Testing: Need QA inspection before launching digital presence.",
        "maps_has_site": "🐛 Bug & Performance Audit: Site shows structural errors; offer full QA test report.",
        "fb_req": "🧪 QA Testing Gig: Looking for automated/manual tester for app/web project."
    },
    {
        "id": "seo",
        "tags": ["seo", "search engine optimization", "backlinks", "on-page seo", "off-page seo"],
        "demo": "https://demo-seo-report.agency-preview.com",
        "maps_no_site": "🔍 Unindexed Business: Zero organic search visibility; pitch complete SEO package.",
        "maps_has_site": "🔍 Missing SEO Meta Tags: Lacks meta tags/descriptions. Ideal candidate for organic SEO audit.",
        "fb_req": "📈 SEO Client Request: Seeking SEO specialist for keyword ranking and backlink strategy."
    },
    {
        "id": "gmb_local_seo",
        "tags": ["gmb", "google my business", "google maps ranking", "local seo", "map pack"],
        "demo": "https://demo-seo-report.agency-preview.com",
        "maps_no_site": "📍 Unclaimed/Unoptimized Maps Listing: Pitch Google Business Profile claim & top 3 map pack ranking.",
        "maps_has_site": "📍 Local SEO Optimization: Boost local citations, reviews, and Google Maps traffic.",
        "fb_req": "📍 Local Business Expansion: Pitch GMB ranking and local customer acquisition."
    },
    {
        "id": "smm",
        "tags": ["smm", "social media marketing", "social media manager", "instagram marketing"],
        "demo": "https://demo-social-kit.agency-preview.com",
        "maps_no_site": "📱 Social Media Client: Lacks web presence; highly dependent on SMM & Instagram growth.",
        "maps_has_site": "📱 Social Funnel Setup: Connect website with Instagram/Facebook content management.",
        "fb_req": "🔥 Active Social Lead: Looking for dedicated Social Media Manager for content & growth."
    },
    {
        "id": "facebook_ads",
        "tags": ["facebook ads", "fb ads", "meta ads", "instagram ads", "ad campaigns"],
        "demo": "https://demo-social-kit.agency-preview.com",
        "maps_no_site": "🎯 Paid Ads Prospect: Business relies on local traffic; pitch targeted Meta Lead Gen Ads.",
        "maps_has_site": "🎯 Retargeting Ads Needed: Pitch Facebook Pixel installation & retargeting ad campaigns.",
        "fb_req": "🎯 Meta Ads Client: Looking for media buyer/ads expert for scaling sales."
    },
    {
        "id": "google_ads",
        "tags": ["google ads", "ppc", "sem", "google adwords", "pay per click"],
        "demo": "https://demo-seo-report.agency-preview.com",
        "maps_no_site": "💰 High Intent Leads: Business needs instant leads; offer Google Search Ads setup.",
        "maps_has_site": "💰 PPC Campaign Audit: Pitch high-converting landing page & Google AdWords campaign.",
        "fb_req": "💰 PPC Lead: Seeking Google Ads specialist for ROI-focused ad campaigns."
    },
    {
        "id": "email_marketing",
        "tags": ["email marketing", "klaviyo", "mailchimp", "email sequence", "cold email"],
        "demo": "https://demo-social-kit.agency-preview.com",
        "maps_no_site": "📧 Customer Retention Setup: Offer email newsletter setup for offline customer list.",
        "maps_has_site": "📧 Email Automation Missing: No email capture form detected. Pitch Klaviyo/Mailchimp sequences.",
        "fb_req": "📧 Email Copy/Klaviyo Specialist needed for automated abandoned cart flows."
    },
    {
        "id": "copywriting",
        "tags": ["copywriting", "sales copy", "landing page copy", "ad copy", "email copy"],
        "demo": "https://demo-branding.agency-preview.com",
        "maps_no_site": "✍️ Brand Messaging: Needs persuasive sales copy for business launch.",
        "maps_has_site": "✍️ Low Conversion Copy: Website text is generic; offer sales copywriting overhaul.",
        "fb_req": "✍️ Copywriter Required: Looking for ad copy or high-converting sales page writer."
    },
    {
        "id": "lead_generation",
        "tags": ["lead generation", "b2b leads", "cold outreach", "prospecting", "data scraping"],
        "demo": "https://demo-seo-report.agency-preview.com",
        "maps_no_site": "🎯 B2B Target: Local service provider looking for B2B client acquisition.",
        "maps_has_site": "🎯 Lead Funnel Missing: Offer automated lead scraping and cold outreach system.",
        "fb_req": "🎯 Lead Gen Specialist needed for B2B appointment setting and targeted lead list."
    },
    {
        "id": "influencer_marketing",
        "tags": ["influencer marketing", "influencer outreach", "brand deals", "ugc creator"],
        "demo": "https://demo-social-kit.agency-preview.com",
        "maps_no_site": "🌟 Brand Outreach: Local brand candidate for UGC creator & influencer campaigns.",
        "maps_has_site": "🌟 Social Proof Boost: Add influencer testimonials & UGC video widgets to website.",
        "fb_req": "🌟 UGC / Influencer Outreach manager needed for brand awareness campaigns."
    },
    {
        "id": "sales_closing",
        "tags": ["sales", "cold calling", "appointment setting", "telemarketing", "sales closer"],
        "demo": "https://demo-social-kit.agency-preview.com",
        "maps_no_site": "📞 Sales Outreach: Pitch cold calling and inbound call booking services.",
        "maps_has_site": "📞 Lead Conversion Failure: High traffic but low sales; pitch professional sales closers.",
        "fb_req": "📞 Appointment Setter / Sales Closer required for high-ticket closing."
    },
    {
        "id": "graphic_design",
        "tags": ["graphic design", "graphics", "photoshop", "illustrator", "canva", "poster", "banner"],
        "demo": "https://demo-branding.agency-preview.com",
        "maps_no_site": "🎨 Marketing Collateral: Needs flyers, promotional banners, and social posts.",
        "maps_has_site": "🎨 Outdated Visuals: Offer professional website graphics & vector asset updates.",
        "fb_req": "🎨 Graphic Designer Needed: Looking for graphic artist for daily social banners."
    },
    {
        "id": "logo_branding",
        "tags": ["logo design", "branding", "brand identity", "corporate identity", "brand guide"],
        "demo": "https://demo-branding.agency-preview.com",
        "maps_no_site": "🔥 Brand Creation: New business needing professional logo, brand guidelines & stationery.",
        "maps_has_site": "✨ Brand Refresh: Rebrand low-res logos into modern vector corporate brand identities.",
        "fb_req": "✨ Branding Gig: Client asking for complete brand identity package & logo vectorization."
    },
    {
        "id": "video_editing",
        "tags": ["video editing", "premiere pro", "capcut", "reels editing", "youtube video editor"],
        "demo": "https://demo-branding.agency-preview.com",
        "maps_no_site": "🎬 Short-Form Video Prospect: Pitch TikTok, Instagram Reels, and YouTube Shorts editing.",
        "maps_has_site": "🎬 Video Landing Page: Add promotional brand video edits to website hero section.",
        "fb_req": "🎬 Video Editor Wanted: Seeking editor for Reels, TikToks, and YouTube content."
    },
    {
        "id": "motion_graphics",
        "tags": ["motion graphics", "after effects", "2d animation", "3d animation", "explainer video"],
        "demo": "https://demo-branding.agency-preview.com",
        "maps_no_site": "💫 Explainer Video Needs: Pitch 60-second animated business introduction video.",
        "maps_has_site": "💫 Animated Web UI: Add After Effects web animations (Lottie JSON) for higher engagement.",
        "fb_req": "💫 Motion Designer Needed: Seeking 2D/3D animator for product explainer video."
    },
    {
        "id": "content_writing",
        "tags": ["content writing", "article writing", "blog writing", "ghostwriting", "copywriter"],
        "demo": "https://demo-seo-report.agency-preview.com",
        "maps_no_site": "📰 Corporate Communications: Business needs profile writing and press release.",
        "maps_has_site": "📰 Dead Blog Section: Blog inactive; offer monthly SEO article writing packages.",
        "fb_req": "📰 Content Writer Wanted: Looking for regular blog posts and web article writer."
    },
    {
        "id": "voiceover",
        "tags": ["voiceover", "voice actor", "audio narration", "podcast intro", "dubbing"],
        "demo": "https://demo-branding.agency-preview.com",
        "maps_no_site": "🎙️ IVR / Phone System: Pitch professional telephone IVR greeting & audio branding.",
        "maps_has_site": "🎙️ Website Voice Narration: Add professional voiceover to promotional product videos.",
        "fb_req": "🎙️ Voiceover Artist Required: Seeking commercial voice actor for video ad."
    },
    {
        "id": "photography",
        "tags": ["photography", "event photography", "product photography", "portrait", "photographer"],
        "demo": "https://demo-branding.agency-preview.com",
        "maps_no_site": "📸 Commercial Shoot Candidate: Requires HD product or facility photography.",
        "maps_has_site": "📸 Low-Quality Stock Photos: Replace generic stock images with real commercial photos.",
        "fb_req": "📸 Photographer Required: Looking for local product or event photographer."
    },
    {
        "id": "videography",
        "tags": ["videography", "video production", "cinematographer", "promo video"],
        "demo": "https://demo-branding.agency-preview.com",
        "maps_no_site": "🎥 Commercial Video Shoot: Candidate for local promotional commercial shoot.",
        "maps_has_site": "🎥 HD Video Background: Pitch custom video production for website header.",
        "fb_req": "🎥 Videographer Hiring: Seeking videographer for promotional brand shoot."
    },
    {
        "id": "podcast_production",
        "tags": ["podcast", "audio editing", "podcast editing", "sound design", "podcast production"],
        "demo": "https://demo-branding.agency-preview.com",
        "maps_no_site": "🎙️ Brand Podcast Setup: Pitch branded podcast creation for corporate authority.",
        "maps_has_site": "🎙️ Audio Branding: Integrate podcast player widget and audio cleanup to site.",
        "fb_req": "🎙️ Podcast Audio Editor needed for noise reduction and episode mixing."
    },
    {
        "id": "three_d_modeling",
        "tags": ["3d modeling", "blender", "3d render", "architectural rendering", "3d product"],
        "demo": "https://demo-branding.agency-preview.com",
        "maps_no_site": "🧊 3D Visualization: Pitch 3D product renders for physical items.",
        "maps_has_site": "🧊 Interactive 3D Model: Add ThreeJS / WebGL 3D product viewer to website.",
        "fb_req": "🧊 3D Artist Required: Looking for Blender/Maya specialist for CAD/product renders."
    },
    {
        "id": "virtual_assistant",
        "tags": ["virtual assistant", "va", "admin support", "data entry", "executive assistant"],
        "demo": "https://demo-web.agency-preview.com",
        "maps_no_site": "📋 Administrative Bottleneck: Pitch virtual assistant for booking and phone queries.",
        "maps_has_site": "📋 Back-Office Automation: Help integrate CRM data entry and appointment scheduling.",
        "fb_req": "📋 Executive VA Wanted: Seeking dedicated Virtual Assistant for email & daily ops."
    },
    {
        "id": "accounting_bookkeeping",
        "tags": ["accounting", "bookkeeping", "quickbooks", "xero", "financial management", "tax"],
        "demo": "https://demo-web.agency-preview.com",
        "maps_no_site": "📊 Financial Setup: Pitch QuickBooks/Xero setup for local business transactions.",
        "maps_has_site": "📊 Invoicing Integration: Connect website sales with automated cloud accounting.",
        "fb_req": "📊 Accountant / Bookkeeper Needed for tax filings, payroll, and monthly audit."
    },
    {
        "id": "customer_support",
        "tags": ["customer support", "live chat", "helpdesk", "customer service", "zendesk"],
        "demo": "https://demo-web.agency-preview.com",
        "maps_no_site": "💬 Support Operations: Pitch 24/7 outsourced live chat support team.",
        "maps_has_site": "💬 No Live Chat: Missing customer support widget; pitch Zendesk / LiveChat setup.",
        "fb_req": "💬 Customer Support Reps wanted for handling tickets and customer calls."
    },
    {
        "id": "project_management",
        "tags": ["project management", "trello", "jira", "asana", "scrum master", "agile"],
        "demo": "https://demo-web.agency-preview.com",
        "maps_no_site": "📐 Process Organization: Help structure business ops in Asana/Trello.",
        "maps_has_site": "📐 Workflow Integration: Connect website leads directly to project management board.",
        "fb_req": "📐 Project Manager / Scrum Master required to oversee agency team deliverables."
    },
    {
        "id": "hr_recruitment",
        "tags": ["hr", "human resources", "recruitment", "talent acquisition", "hiring manager"],
        "demo": "https://demo-web.agency-preview.com",
        "maps_no_site": "👥 Staffing Need: Local business expanding; offer recruitment/screening services.",
        "maps_has_site": "👥 Careers Page Missing: Build automated job application portal on business website.",
        "fb_req": "👥 Recruiter / HR Specialist needed for candidate sourcing and interviewing."
    },
   {
        "id": "legal_consulting",
        "tags": ["legal", "lawyer", "contract drafting", "terms of service", "trademark"],
        "demo": "https://demo-lawfirm.agency-preview.com",
        "maps_no_site": "⚖️ Legal Compliance: Needs legal disclaimer, business registration & contract templates.",
        "maps_has_site": "⚖️ Missing Legal Pages: Website missing Privacy Policy, Terms, and GDPR compliance.",
        "fb_req": "⚖️ Legal Advisor Needed for drafting client agreements and trademark filing."
    },
    {
        "id": "financial_analysis",
        "tags": ["financial analysis", "financial model", "business plan", "valuation", "pitch deck"],
        "demo": "https://demo-web.agency-preview.com",
        "maps_no_site": "📈 Investment Readiness: Needs professional business plan & financial projection.",
        "maps_has_site": "📈 Investor Pitch Deck: Convert business web data into high-converting investor pitch deck.",
        "fb_req": "📈 Financial Analyst Needed: Seeking expert to build 5-year financial model."
    },
    {
        "id": "business_consulting",
        "tags": ["business consulting", "business strategy", "growth strategy", "operations management"],
        "demo": "https://demo-web.agency-preview.com",
        "maps_no_site": "💼 Growth Strategy: Local business candidate for operational & sales consulting.",
        "maps_has_site": "💼 Conversion Rate Audit: Offer business model optimization & revenue consulting.",
        "fb_req": "💼 Business Consultant Wanted: Seeking strategist to streamline company operations."
    },
    {
        "id": "market_research",
        "tags": ["market research", "competitor analysis", "industry research", "feasibility study"],
        "demo": "https://demo-seo-report.agency-preview.com",
        "maps_no_site": "🔬 Market Expansion: Needs feasibility study before launching in new city.",
        "maps_has_site": "🔬 Competitor Benchmark: Provide report on competitor website traffic and positioning.",
        "fb_req": "🔬 Market Researcher Required for competitor analysis and industry trends report."
    },
    {
        "id": "data_analysis",
        "tags": ["data analysis", "data analyst", "power bi", "tableau", "excel automation"],
        "demo": "https://demo-web.agency-preview.com",
        "maps_no_site": "📊 Data Organization: Convert messy offline registers into clean Excel/PowerBI dashboards.",
        "maps_has_site": "📊 Analytics Dashboard Missing: Setup Google Analytics 4 (GA4) and Looker Studio reports.",
        "fb_req": "📊 Data Analyst / PowerBI Expert needed for automated business reporting dashboards."
    },
    {
        "id": "ai_automation",
        "tags": ["ai", "machine learning", "chatgpt", "prompt engineering", "n8n", "make.com", "ai automation"],
        "demo": "https://demo-web.agency-preview.com",
        "maps_no_site": "🤖 AI Workflow Setup: Pitch n8n/Make.com workflows for automated customer handling.",
        "maps_has_site": "🤖 AI Integration: Add ChatGPT-powered AI customer assistant widget to site.",
        "fb_req": "🤖 AI Specialist Needed: Looking to automate manual tasks via LLMs & Make.com."
    },
    {
        "id": "chatbot_dev",
        "tags": ["chatbot", "manychat", "dialogflow", "whatsapp bot", "customer service bot"],
        "demo": "https://demo-web.agency-preview.com",
        "maps_no_site": "💬 WhatsApp Automation: Build automated WhatsApp bot for booking inquiries.",
        "maps_has_site": "💬 Website Chatbot Missing: Pitch ManyChat / Dialogflow bot for instant customer capture.",
        "fb_req": "💬 Chatbot Developer Wanted for Messenger & WhatsApp auto-reply flows."
    },
    {
        "id": "interior_design",
        "tags": ["interior design", "autocad", "sketchup", "home staging", "space planning"],
        "demo": "https://demo-realty.agency-preview.com",
        "maps_no_site": "🏠 Spatial Planning: Local venue/office needing commercial interior design portfolio.",
        "maps_has_site": "🏠 Portfolio Showcase: Display 3D interior renders on business website.",
        "fb_req": "🏠 Interior Designer Hiring: Seeking designer for commercial or residential project."
    },
    {
        "id": "architecture",
        "tags": ["architecture", "architectural drafting", "blueprint", "building design", "revit"],
        "demo": "https://demo-realty.agency-preview.com",
        "maps_no_site": "🏗️ Blueprint & Permit: Candidate for architectural drafting and approval plans.",
        "maps_has_site": "🏗️ Architectural Portfolio: Upgrade site to showcase Revit/AutoCAD blueprints.",
        "fb_req": "🏗️ Architect Needed: Seeking licensed architect for CAD drawings & building plans."
    },
    {
        "id": "translation",
        "tags": ["translation", "translator", "transcription", "subtitles", "language localization"],
        "demo": "https://demo-seo-report.agency-preview.com",
        "maps_no_site": "🌐 Multi-Language Reach: Pitch local translation for non-English customer demographic.",
        "maps_has_site": "🌐 Single Language Website: Pitch multi-language website translation (e.g. English/Arabic/Urdu).",
        "fb_req": "🌐 Translator Required: Looking for native translator for document & web localization."
    },
    {
        "id": "real_estate_services",
        "tags": ["real estate", "property management", "realtor", "property listing", "real estate leads"],
        "demo": "https://demo-realty.agency-preview.com",
        "maps_no_site": "🏢 Property IDX Setup: Pitch custom property listing website with MLS integration.",
        "maps_has_site": "🏢 Lead Capture Upgrade: Add virtual property tour and mortgage calculator widgets.",
        "fb_req": "🏢 Real Estate Lead Gen: Seeking marketer for generating homebuyer leads."
    },
    {
        "id": "event_planning",
        "tags": ["event planning", "wedding planner", "corporate event", "event management"],
        "demo": "https://demo-branding.agency-preview.com",
        "maps_no_site": "🎉 Event Management Setup: Pitch booking portal and digital RSVP system.",
        "maps_has_site": "🎉 Gallery & Booking System: Add interactive event gallery & booking calendar.",
        "fb_req": "🎉 Event Planner Needed: Looking for corporate or wedding event coordinator."
    },
    {
        "id": "fitness_coaching",
        "tags": ["fitness coach", "personal trainer", "nutritionist", "workout plan", "dietitian"],
        "demo": "https://demo-medical.agency-preview.com",
        "maps_no_site": "🏋️ Online Fitness Platform: Pitch digital fitness coaching app & workout store.",
        "maps_has_site": "🏋️ Membership Funnel: Add automated fitness meal plan purchase & booking system.",
        "fb_req": "🏋️ Personal Trainer / Nutritionist Needed for online client coaching."
    },
    {
        "id": "tutoring_elearning",
        "tags": ["tutoring", "online tutor", "course creation", "lms", "teachable", "udemy"],
        "demo": "https://demo-web.agency-preview.com",
        "maps_no_site": "📚 E-Learning Portal: Build LMS (Learning Management System) for offline institute.",
        "maps_has_site": "📚 Course Selling System: Convert website into digital course platform with student logins.",
        "fb_req": "📚 Course Creator / Tutor Required for online subject lectures."
    },
    {
        "id": "music_audio",
        "tags": ["music production", "beat making", "mixing and mastering", "sound engineer", "jingle"],
        "demo": "https://demo-branding.agency-preview.com",
        "maps_no_site": "🎵 Audio Branding: Pitch custom commercial audio jingles for business.",
        "maps_has_site": "🎵 Audio Player Integration: Add embedded audio portfolio and track player.",
        "fb_req": "🎵 Music Producer / Audio Engineer required for mixing and sound design."
    },
    {
        "id": "logistics_supply",
        "tags": ["logistics", "supply chain", "freight forwarding", "inventory management", "shipping"],
        "demo": "https://demo-web.agency-preview.com",
        "maps_no_site": "📦 Freight Management: Pitch online shipment tracking portal for local logistics.",
        "maps_has_site": "📦 Tracking API Integration: Connect site to real-time shipment tracking APIs.",
        "fb_req": "📦 Logistics Coordinator Needed for freight management and inventory tracking."
    }
]

# Default fallback if user skill is completely unique
DEFAULT_SKILL_MATCH = {
    "id": "generic_service",
    "tags": [],
    "demo": "https://myportfolio.com",
    "maps_no_site": "🔥 Target Business: Lacks official website. Candidate for digital setup.",
    "maps_has_site": "⚠️ Target Client: Digital presence found. Opportunity for service optimization.",
    "fb_req": "📱 Social Client Request: Active on social channels, pitch specialized services."
}

def match_skill_database(user_skill):
    s_clean = user_skill.lower().strip()
    for skill_obj in SKILL_DATABASE:
        for tag in skill_obj["tags"]:
            if tag in s_clean:
                return skill_obj
    return DEFAULT_SKILL_MATCH

# ==========================================
# WORLDWIDE MAJOR CITIES DATABASE
# ==========================================
WORLD_CITIES = {
    "Pakistan": ["Lahore", "Karachi", "Islamabad", "Rawalpindi", "Faisalabad", "Multan", "Peshawar", "Sialkot", "Gujranwala", "Hyderabad", "Quetta", "Bahawalpur", "Sargodha", "Sukkur", "Jhang"],
    "United States": ["New York", "Los Angeles", "Chicago", "Houston", "Phoenix", "Philadelphia", "San Antonio", "San Diego", "Dallas", "San Jose", "Austin", "Jacksonville", "Fort Worth", "Columbus", "Charlotte", "Miami", "Atlanta"],
    "United Kingdom": ["London", "Birmingham", "Manchester", "Leeds", "Glasgow", "Liverpool", "Newcastle", "Sheffield", "Bristol", "Belfast", "Edinburgh", "Leicester", "Coventry"],
    "United Arab Emirates": ["Dubai", "Abu Dhabi", "Sharjah", "Ajman", "Ras Al Khaimah", "Fujairah", "Al Ain"],
    "Canada": ["Toronto", "Montreal", "Vancouver", "Calgary", "Edmonton", "Ottawa", "Winnipeg", "Quebec City", "Hamilton"],
    "Australia": ["Sydney", "Melbourne", "Brisbane", "Perth", "Adelaide", "Gold Coast", "Canberra", "Newcastle"],
    "Saudi Arabia": ["Riyadh", "Jeddah", "Mecca", "Medina", "Dammam", "Khobar", "Tabuk"],
    "Germany": ["Berlin", "Hamburg", "Munich", "Cologne", "Frankfurt", "Stuttgart", "Düsseldorf"],
    "India": ["Mumbai", "Delhi", "Bangalore", "Hyderabad", "Ahmedabad", "Chennai", "Kolkata", "Surat", "Pune", "Jaipur"]
}
def get_city_list(country_name):
    c_title = country_name.strip().title()
    if c_title in WORLD_CITIES:
        return WORLD_CITIES[c_title]
    return [c_title, f"Central {c_title}", f"North {c_title}", f"South {c_title}", f"East {c_title}", f"West {c_title}", f"Capital Region {c_title}"]

# ==========================================
# FAST MINI-AUDIT ENGINE
# ==========================================
def deep_audit_website(website_url):
    audit_data = {
        "emails": [],
        "phones": [],
        "audit_notes": [],
        "has_ssl": True,
        "is_responsive": True,
        "has_seo": True
    }
    if not website_url or not website_url.startswith("http"):
        return audit_data

    try:
        if website_url.startswith("http://"):
            audit_data["has_ssl"] = False
            audit_data["audit_notes"].append("❌ No SSL (HTTP)")

        res = requests.get(website_url, headers=WEB_HEADERS, timeout=2.0)
        if res.status_code == 200:
            html = res.text

            emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', html)
            audit_data["emails"] = list(set([e for e in emails if not e.lower().endswith(('.png', '.jpg', '.jpeg', '.svg', '.gif'))]))[:2]

            phones = re.findall(r'(\+?\d{1,4}[-.\s]?\(?\d{1,3}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4})', html)
            audit_data["phones"] = list(set([p for p in phones if len(p) >= 10]))[:2]

            if "viewport" not in html.lower():
                audit_data["is_responsive"] = False
                audit_data["audit_notes"].append("📱 No Mobile Viewport")

            if 'name="description"' not in html.lower() and "name='description'" not in html.lower():
                audit_data["has_seo"] = False
                audit_data["audit_notes"].append("🔍 Missing Meta Description")

    except Exception:
        pass

    return audit_data

# ==========================================
# SKILL REQUIREMENT GENERATOR
# ==========================================
def extract_business_requirement(item_type, has_website, audit_info, user_skill):
    matched = match_skill_database(user_skill)
    audit_notes = audit_info.get("audit_notes", [])

    if item_type == "Facebook":
        return matched["fb_req"]

    if not has_website:
        return matched["maps_no_site"]
    elif audit_notes:
        return f"{matched['maps_has_site']} (Issues: {', '.join(audit_notes)})"
    else:
        return matched["maps_has_site"]

# ==========================================
# SOURCE 1: GOOGLE MAPS BULK ENGINE
# ==========================================
def fetch_google_maps_leads(skill, country, niche):
    leads = []
    seen = set()
    cities = get_city_list(country)
    niche_prefix = f"{niche} " if niche and niche != "All Niches" else ""

    search_terms = []
    for city in cities:
        search_terms.append(f"{niche_prefix}{skill} in {city} {country}")
        search_terms.append(f"{niche_prefix}agency in {city} {country}")
        search_terms.append(f"{niche_prefix}services in {city} {country}")
        search_terms.append(f"{niche_prefix}company {city} {country}")

    def query_nominatim(q_term):
        results = []
        try:
            url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(q_term)}&format=json&addressdetails=1&extratags=1&limit=50"
            res = requests.get(url, headers=WEB_HEADERS, timeout=4)
            if res.status_code == 200:
                data = res.json()
                for item in data:
                    display_name = item.get("display_name", "")
                    b_name = display_name.split(",")[0].strip()

                    if b_name.lower() in seen or len(b_name) < 3:
                        continue
                    seen.add(b_name.lower())

                    extratags = item.get("extratags", {}) or {}
                    website = extratags.get("website") or extratags.get("contact:website", "")
                    direct_email = extratags.get("email") or extratags.get("contact:email", "")
                    
                    has_website = bool(website)
                    audit_info = deep_audit_website(website) if has_website else {}
                    
                    if not direct_email and audit_info.get("emails"):
                        direct_email = audit_info["emails"][0]

                    req_text = extract_business_requirement("Google Maps", has_website, audit_info, skill)

                    lat, lon = item.get("lat"), item.get("lon")
                    maps_link = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}" if lat and lon else f"https://www.google.com/maps/search/{urllib.parse.quote(b_name + ' ' + country)}"

                    results.append({
                        "platform": "Google Maps",
                        "title": b_name,
                        "requirement": req_text,
                        "website": website,
                        "email": direct_email or "Not Public",
                        "phones": audit_info.get("phones", []),
                        "audit_notes": audit_info.get("audit_notes", []),
                        "action_link": maps_link,
                        "badge": "Google Business",
                        "lead_type": "maps"
                    })
        except Exception:
            pass
        return results

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(query_nominatim, term) for term in search_terms]
        for future in as_completed(futures):
            leads.extend(future.result())

    return leads

# ==========================================
# SOURCE 2: FACEBOOK BUSINESS & PAGES BULK ENGINE
# ==========================================
def fetch_facebook_leads(skill, country, niche):
    leads = []
    seen = set()
    cities = get_city_list(country)
    niche_prefix = f"{niche} " if niche and niche != "All Niches" else ""

    fb_queries = []
    for city in cities[:8]:
        fb_queries.append(f'site:facebook.com/pages "{niche_prefix}{skill}" "{city}" "{country}"')
        fb_queries.append(f'site:facebook.com "{niche_prefix}business" "{city}" "{country}" "contact"')
        fb_queries.append(f'site:facebook.com "{skill}" ("hiring" OR "looking for agency" OR "need client") "{city}"')

    def query_facebook_rss(query):
        results = []
        try:
            rss_url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en-US&gl=US&ceid=US:en"
            res = requests.get(rss_url, headers=WEB_HEADERS, timeout=4)
            if res.status_code == 200:
                feed = feedparser.parse(res.content)
                for entry in feed.entries[:20]:
                    title = clean_html(entry.title)
                    summary = clean_html(getattr(entry, 'summary', ''))

                    clean_title = title.replace("- Facebook", "").strip()
                    if clean_title.lower() in seen or len(clean_title) < 3:
                        continue
                    seen.add(clean_title.lower())

                    req_text = extract_business_requirement("Facebook", False, {}, skill)

                    results.append({
                        "platform": "Facebook",
                        "title": clean_title,
                        "requirement": f"{req_text} Details: {summary[:150]}...",
                        "website": "",
                        "email": "Message on Facebook",
                        "phones": [],
                        "audit_notes": [],
                        "action_link": entry.link,
                        "badge": "Facebook Page / Post",
                        "lead_type": "facebook"
                    })
        except Exception:
            pass
        return results

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(query_facebook_rss, q) for q in fb_queries]
        for future in as_completed(futures):
            leads.extend(future.result())

    return leads

# ==========================================
# MAIN API ROUTE
# ==========================================
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/leads', methods=['GET'])
def get_leads():
    skill = request.args.get('skill', 'Web Development').strip()
    country = request.args.get('country', 'Pakistan').strip()
    niche = request.args.get('niche', 'All Niches').strip()

    cached = get_from_cache(skill, country, niche)
    if cached:
        cached["is_cached"] = True
        return jsonify(cached)

    matched_skill = match_skill_database(skill)

    with ThreadPoolExecutor(max_workers=2) as executor:
        f_maps = executor.submit(fetch_google_maps_leads, skill, country, niche)
        f_fb = executor.submit(fetch_facebook_leads, skill, country, niche)

        maps_results = f_maps.result()
        fb_results = f_fb.result()

    all_leads = maps_results + fb_results

    response_payload = {
        "status": "success",
        "is_cached": False,
        "total_found": len(all_leads),
        "demo_portfolio": matched_skill["demo"],
        "matched_skill_id": matched_skill["id"],
        "leads": all_leads
    }

    save_to_cache(skill, country, niche, response_payload)
    return jsonify(response_payload)

# ==========================================
# AI PITCH GENERATOR
# ==========================================
@app.route('/api/ai_pitch', methods=['POST'])
def generate_ai_pitch():
    data = request.json or {}
    lead_title = data.get("lead_title", "")
    lead_desc = data.get("lead_desc", "")
    audit_notes = data.get("audit_notes", [])
    step = data.get("step", "day1")
    user_portfolio = data.get("portfolio", "https://myportfolio.com")

    audit_str = f" Business Requirement/Issue: {', '.join(audit_notes)}." if audit_notes else ""

    prompts = {
        "day1": f"Write a compelling 3-sentence outreach proposal for '{lead_title}'. Business Context: {lead_desc}.{audit_str} Offer live portfolio link: {user_portfolio}",
        "day3": f"Write a quick 2-sentence follow-up message to '{lead_title}' checking if they reviewed the proposal. Portfolio link: {user_portfolio}",
        "day7": f"Write a final high-value offer message for '{lead_title}' providing a free 15-minute consultation. Portfolio link: {user_portfolio}"
    }

    prompt = prompts.get(step, prompts["day1"])

    if not ai_client:
        fallback = f"Hello {lead_title}!\n\nI reviewed your business setup and noticed great growth opportunities. Check out our live portfolio: {user_portfolio}\nLet's discuss how we can help!"
        return jsonify({"status": "success", "pitch": fallback, "mode": "template"})

    try:
        response = ai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        pitch_text = response.text if response and hasattr(response, 'text') else "Proposal generation failed."
        return jsonify({"status": "success", "pitch": pitch_text, "mode": "ai"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
