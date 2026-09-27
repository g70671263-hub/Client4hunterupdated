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
# 1. MEMORY CACHE SYSTEM (15 MIN TTL)
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
# 2. 51 SKILLS MATRIX & MULTI-TAGS DATABASE
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
        "id": "graphic_design",
        "tags": ["graphic design", "graphics", "photoshop", "illustrator", "canva", "poster", "banner"],
        "demo": "https://demo-branding.agency-preview.com",
        "maps_no_site": "🎨 Marketing Collateral: Needs flyers, promotional banners, and social posts.",
        "maps_has_site": "🎨 Outdated Visuals: Offer professional website graphics & vector asset updates.",
        "fb_req": "🎨 Graphic Designer Needed: Looking for graphic artist for daily social banners."
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
        "id": "ai_automation",
        "tags": ["ai", "machine learning", "chatgpt", "prompt engineering", "n8n", "make.com", "ai automation"],
        "demo": "https://demo-web.agency-preview.com",
        "maps_no_site": "🤖 AI Workflow Setup: Pitch n8n/Make.com workflows for automated customer handling.",
        "maps_has_site": "🤖 AI Integration: Add ChatGPT-powered AI customer assistant widget to site.",
        "fb_req": "🤖 AI Specialist Needed: Looking to automate manual tasks via LLMs & Make.com."
    }
]

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
# 3. EXPANDED CITIES DATABASE (NO-SKIP FIX)
# ==========================================
WORLD_CITIES = {
    "Pakistan": ["Lahore", "Karachi", "Islamabad", "Rawalpindi", "Faisalabad", "Multan", "Peshawar", "Sialkot", "Gujranwala", "Hyderabad", "Quetta", "Bahawalpur", "Sargodha", "Sukkur"],
    "United States": ["New York", "Los Angeles", "Chicago", "Houston", "Phoenix", "Philadelphia", "San Antonio", "San Diego", "Dallas", "Austin", "Miami", "Atlanta"],
    "United Kingdom": ["London", "Birmingham", "Manchester", "Leeds", "Glasgow", "Liverpool", "Edinburgh", "Bristol"],
    "United Arab Emirates": ["Dubai", "Abu Dhabi", "Sharjah", "Ajman", "Ras Al Khaimah"],
    "Canada": ["Toronto", "Montreal", "Vancouver", "Calgary", "Edmonton", "Ottawa"],
    "Australia": ["Sydney", "Melbourne", "Brisbane", "Perth", "Adelaide"]
}

def get_city_list(country_name):
    c_title = country_name.strip().title()
    if c_title in WORLD_CITIES:
        return WORLD_CITIES[c_title]
    return [c_title, f"Central {c_title}", f"North {c_title}", f"South {c_title}", f"East {c_title}", f"West {c_title}"]

# ==========================================
# 4. SITE AUDITOR & REQ GENERATOR
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

        res = requests.get(website_url, headers=WEB_HEADERS, timeout=2.5)
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
# 5. SCRAPERS (GOOGLE MAPS & FACEBOOK)
# ==========================================
def fetch_google_maps_leads(skill, country, niche):
    leads = []
    seen = set()
    cities = get_city_list(country)
    niche_prefix = f"{niche} " if niche and niche != "All Niches" else ""

    # Micro-queries per city to eliminate skipping issues
    search_terms = []
    for city in cities:
        search_terms.append(f"{niche_prefix}{skill} in {city} {country}")
        search_terms.append(f"{niche_prefix}agency in {city} {country}")
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
                    phone_no = extratags.get("phone") or extratags.get("contact:phone", "")

                    has_website = bool(website)
                    audit_info = deep_audit_website(website) if has_website else {}
                    
                    extracted_emails = audit_info.get("emails", [])
                    extracted_phones = audit_info.get("phones", [])
                    
                    if direct_email and direct_email not in extracted_emails:
                        extracted_emails.append(direct_email)
                    if phone_no and phone_no not in extracted_phones:
                        extracted_phones.append(phone_no)

                    req_text = extract_business_requirement("Google Maps", has_website, audit_info, skill)

                    # Red Pati Rule: Missing website OR critical audit errors = High Priority (Red Pati)
                    is_red_pati = (not has_website) or (len(audit_info.get("audit_notes", [])) > 0)

                    lat, lon = item.get("lat"), item.get("lon")
                    maps_link = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}" if lat and lon else f"https://www.google.com/maps/search/{urllib.parse.quote(b_name + ' ' + country)}"

                    results.append({
                        "platform": "Google Maps",
                        "title": b_name,
                        "requirement": req_text,
                        "website": website,
                        "email": extracted_emails[0] if extracted_emails else "Not Public",
                        "phones": extracted_phones,
                        "whatsapp": extracted_phones[0] if extracted_phones else "",
                        "audit_notes": audit_info.get("audit_notes", []),
                        "action_link": maps_link,
                        "badge": "Google Business",
                        "lead_type": "maps",
                        "red_pati": is_red_pati,
                        "high_chance": is_red_pati
                    })
        except Exception:
            pass
        return results

with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [executor.submit(query_nominatim, term) for term in search_terms]
        for future in as_completed(futures):
            leads.extend(future.result())

    return leads

def fetch_facebook_leads(skill, country, niche):
    leads = []
    seen = set()
    cities = get_city_list(country)
    niche_prefix = f"{niche} " if niche and niche != "All Niches" else ""

    fb_queries = [
        f'site:facebook.com/pages "{niche_prefix}{skill}" "{city}" "{country}"'
        for city in cities[:6]
    ]

    def query_facebook_rss(query):
        results = []
        try:
            rss_url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en-US&gl=US&ceid=US:en"
            res = requests.get(rss_url, headers=WEB_HEADERS, timeout=4)
            if res.status_code == 200:
                feed = feedparser.parse(res.content)
                for entry in feed.entries[:15]:
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
                        "requirement": f"{req_text} Details: {summary[:120]}...",
                        "website": "",
                        "email": "Message on Facebook",
                        "phones": [],
                        "whatsapp": "",
                        "audit_notes": [],
                        "action_link": entry.link,
                        "badge": "Facebook Page",
                        "lead_type": "facebook",
                        "red_pati": True, # High conversion social leads default to Red Pati
                        "high_chance": True
                    })
        except Exception:
            pass
        return results

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(query_facebook_rss, q) for q in fb_queries]
        for future in as_completed(futures):
            leads.extend(future.result())

    return leads

# ==========================================
# 6. 3-TIER PRIORITY SORTING LOGIC
# ==========================================
def sort_leads(leads):
    """
    Priority Order:
    1. Red Pati / High Chance (Top Priority)
    2. Extracted Contacts (Email, Phone, WhatsApp)
    3. Remaining leads
    """
    def priority_key(lead):
        is_red_pati = lead.get('red_pati', False) or lead.get('high_chance', False)
        
        has_email = lead.get('email') and lead.get('email') != "Not Public"
        has_phone = bool(lead.get('phones')) or bool(lead.get('whatsapp'))
        has_contact = has_email or has_phone

        if is_red_pati:
            return 1
        elif has_contact:
            return 2
        else:
            return 3

    return sorted(leads, key=priority_key)

# ==========================================
# 7. FLASK ROUTES
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

    raw_leads = maps_results + fb_results
    sorted_leads_data = sort_leads(raw_leads) # 3-Tier Priority Applied Here!

    response_payload = {
        "status": "success",
        "is_cached": False,
        "total_found": len(sorted_leads_data),
        "demo_portfolio": matched_skill["demo"],
        "matched_skill_id": matched_skill["id"],
        "leads": sorted_leads_data
    }

    save_to_cache(skill, country, niche, response_payload)
    return jsonify(response_payload)

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
        "day1": f"Write a compelling 3-sentence outreach proposal for '{lead_title}'. Context: {lead_desc}.{audit_str} Portfolio: {user_portfolio}",
        "day3": f"Write a quick 2-sentence follow-up message to '{lead_title}' checking if they reviewed the proposal. Portfolio: {user_portfolio}",
        "day7": f"Write a final offer message for '{lead_title}' offering a free consultation. Portfolio: {user_portfolio}"
    }

    prompt = prompts.get(step, prompts["day1"])

    if not ai_client:
        fallback = f"Hello {lead_title}!\n\nI noticed great growth opportunities for your business. Check out our live portfolio: {user_portfolio}\nLet's connect!"
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
