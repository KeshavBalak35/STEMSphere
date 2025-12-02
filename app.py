import streamlit as st
from datetime import datetime, date, time, timedelta
import urllib.parse
try:
  from google_auth_oauthlib.flow import InstalledAppFlow
  from googleapiclient.discovery import build
  GOOGLE_LIBS_AVAILABLE = True
except Exception:
  GOOGLE_LIBS_AVAILABLE = False
from zoneinfo import ZoneInfo
import os, csv

# ----------------------------
# Basic site configuration
st.set_page_config(page_title="STEMSphere", page_icon=":rocket:", layout="wide")

# Initialize session state for navigation and selection
params = st.query_params
if 'page' in params:
  st.session_state.setdefault('page', params.get('page', ['Home'])[0])
else:
  st.session_state.setdefault('page', 'Home')
st.session_state.setdefault('selected_program', None)
st.session_state.setdefault('contact_prefill', '')
st.session_state.setdefault('selected_ap_course', None)


# ---------- Styles & Fonts ----------
_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=Poppins:wght@300;400;600;700;800&display=swap');
  :root{
    /* STEMSphere brand palette */
    --accent-1: #146C94; /* deep teal/navy */
    --accent-2: #27A9E0; /* bright cyan */
    --accent-3: #0f4c75; /* darker accent */
    --muted: #586068;
    --page-bg: linear-gradient(180deg,#f8fbfc 0%, #eef8fb 50%, #f3fbff 100%);
    --hero-bg: linear-gradient(120deg, rgba(20,108,148,0.06), rgba(39,169,224,0.03));
    --card-bg: rgba(255,255,255,0.96);
  }

  html, body, [data-testid='stAppViewContainer'] {
    background: var(--page-bg) !important;
    font-family: 'Inter', 'Poppins', system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial;
    color: #0b2230;
    -webkit-font-smoothing:antialiased;
    -moz-osx-font-smoothing:grayscale;
    letter-spacing: -0.1px;
  }

  /* Make heading typography stronger */
  h1, h2, h3, h4 { font-family: 'Poppins', 'Inter', sans-serif; margin:0 0 8px 0; color:var(--accent-3); }
  h1 { font-size:48px; line-height:1.03; font-weight:800; letter-spacing:-0.6px }
  h2 { font-size:28px; line-height:1.1; font-weight:700 }
  h3 { font-size:20px; font-weight:600 }

  .stApp [role='main'] {
    padding-top: 12px;
  }

  /* header */
  .logo {display:flex; align-items:center; gap:14px}
  .logo img {height:68px; padding:6px; border-radius:10px; box-shadow: 0 12px 36px rgba(7,20,34,0.12)}
  .site-title {font-size:20px; font-weight:800; color:var(--accent-1); letter-spacing:0.2px}
  .site-tag {font-size:12px; color:var(--muted); margin-top:-6px}

  /* navbar look */
  .nav {display:flex; gap:10px; align-items:center}
  .nav a {color:var(--muted); text-decoration:none; padding:8px 14px; border-radius:10px; font-weight:600}
  .nav a:hover {background: rgba(31, 182, 255, 0.06); color:var(--accent-2)}

  /* Style Streamlit buttons consistently */
  .stButton>button, div.stButton>button { border-radius:12px; padding:10px 18px; font-weight:700; transition: transform .12s ease, box-shadow .12s ease, opacity .12s ease }
  .stButton>button:hover, div.stButton>button:hover { transform: translateY(-3px); box-shadow: 0 18px 40px rgba(20,108,148,0.08) }

  /* hero */
  .hero {padding:48px; display:flex; gap:28px; align-items:center; background:linear-gradient(180deg, rgba(39,169,224,0.06), rgba(20,108,148,0.03)), var(--hero-bg); border-radius:22px; backdrop-filter: blur(3px);}
  .hero .left {flex:1}
  .hero .right {flex:0.6}
  .hero-cta h1 {font-family: 'Poppins', 'Inter', sans-serif; font-size:48px; font-weight:800; margin-bottom:12px; color: var(--accent-3);}
  .hero p {color:var(--muted); font-size:16px; margin-bottom:16px; max-width:56ch;}

  .btn-primary {background: linear-gradient(90deg,var(--accent-1),var(--accent-2)); color: white; border:none; padding:12px 22px; border-radius:12px; font-weight:700; box-shadow:0 18px 42px rgba(20,108,148,0.14); border: 1px solid rgba(255,255,255,0.06)}
  .btn-primary:hover { transform: translateY(-4px); box-shadow: 0 26px 70px rgba(20,108,148,0.16) }
  .btn-outline {background:transparent; border: 1px solid rgba(15,76,117,0.12); color:var(--accent-1); padding:10px 16px; border-radius:10px; font-weight:600}

  /* cards (glass / elevated) */
  .card {background: linear-gradient(180deg, rgba(255,255,255,0.88), rgba(255,255,255,0.94)); padding:24px; border-radius:16px; box-shadow: 0 22px 60px rgba(12,24,32,0.06); transition: transform .16s cubic-bezier(.2,.8,.2,1), box-shadow .16s ease, border-color .12s ease}
  .card:hover {transform:translateY(-8px); box-shadow: 0 30px 60px rgba(11,20,29,0.12)}

  .stat-pill {background:linear-gradient(90deg, rgba(39,169,224,0.12), rgba(20,108,148,0.06)); padding:8px 14px; border-radius:999px; display:inline-block; font-weight:700; color:var(--accent-3)}

  /* program grid */
  .program-grid {display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:20px}
  .program-card-title {font-family: 'Poppins', 'Inter', sans-serif; font-weight:700; color:#08384a; font-size:18px}
  .program-price {background:linear-gradient(90deg,var(--accent-1),var(--accent-2)); color:white; padding:8px 12px; border-radius:12px; font-weight:700; box-shadow: 0 6px 24px rgba(20,108,148,0.12)}

  /* footer */
  .footer {color:var(--muted); padding:28px; text-align:center; font-size:14px; background:transparent}

  /* testimonials */
  .testi {display:flex; gap:18px; align-items:center}
  .avatar {height:56px; width:56px; border-radius:999px; box-shadow: 0 10px 34px rgba(11,20,29,0.08)}

  /* trust badges */
  .trust-row {display:flex; gap:12px; align-items:center; justify-content:center; margin-top:12px}
  .trust {background:white; padding:10px 14px; border-radius:12px; box-shadow:0 6px 18px rgba(16,24,40,0.06); font-weight:700}

  /* small animations */
  .fade-in {opacity:0; animation:fadeIn 0.9s cubic-bezier(.2,.9,.3,1) forwards}
  @keyframes fadeIn { to {opacity:1} }

  @media (max-width: 900px) {
    .hero {flex-direction:column; align-items:flex-start; padding:28px}
    .hero-cta h1 {font-size:32px}
    h1 {font-size:36px}
  }
</style>
"""

st.markdown(_CSS, unsafe_allow_html=True)


# ---------- Static assets / sample data ----------
LOGO_URL = "assets/stemsphere_logo.png"

AP_COURSES = [
  'AP Computer Science A',
  'AP Calculus AB/BC',
  'AP Physics C E&M',
  'AP Physics C Mechanics',
  'AP Statistics',
  'AP Chemistry',
  'AP Precalculus'
]

PROGRAMS = [
  {"id":1, "title":"SAT/ACT Math Prep", "summary":"12-week math test-prep program, 1:1 tutoring and practice tests", "price":"$50/hour"},
  {"id":2, "title":"College Consulting", "summary":"Guidance on essays, application strategy, shortlisting, and interview prep", "price":"$8,000"},
  {"id":3, "title":"AP Bootcamp", "summary":"Targeted course for AP STEM courses with top scorers as instructors", "price":"$50/hour per course", "courses": AP_COURSES}
]

# ---------- Helper UI components ----------
def header():
  c1, c2 = st.columns([1, 4])
  with c1:
    st.image(LOGO_URL, width=90)
    st.write("**STEMSphere**")
    st.caption("Accelerate elite STEM outcomes")

  with c2:
    # Right-aligned navigation as buttons (set session_state['page'])
    # Show admin button only when ADMIN_PASSWORD is present (keeps page hidden otherwise)
    show_admin = bool(os.getenv('ADMIN_PASSWORD'))
    nav_cols = st.columns([1,1,1,1,1] if show_admin else [1,1,1,1])
    if nav_cols:
      if nav_cols[0].button('Home', key='nav_home'):
        st.session_state['page'] = 'Home'
      if nav_cols[1].button('Programs', key='nav_programs'):
        st.session_state['page'] = 'Programs'
      if nav_cols[2].button('About', key='nav_about'):
        st.session_state['page'] = 'About'
      if nav_cols[3].button('Contact', key='nav_contact'):
        st.session_state['page'] = 'Contact'
      if show_admin and nav_cols[4].button('Admin', key='nav_admin'):
        st.session_state['page'] = 'Admin'


def hero():
  left, right = st.columns([2, 1])
  with left:
    # Show a larger brand logo on the Home page (use PNG)
    if st.session_state.get('page', 'Home') == 'Home':
      st.image(LOGO_URL, width=220)
    st.title("Transform your college journey with data-driven, mentor-led coaching")
    st.write("Personalized pathways for ambitious students — test prep, research mentoring, and application strategy that delivers measurable results.")
    c1, c2 = st.columns([1, 1])
    with c1:
      if st.button("Explore Programs", key='hero_explore'):
        st.session_state['page'] = 'Programs'
    with c2:
      if st.button("Request Consultation", key='hero_request'):
        st.session_state['page'] = 'Contact'

  with right:
    # Display concise outcome metrics
    stat_cols = st.columns([1, 1, 1])
    stat_cols[0].metric(label="1500+ SAT scores", value="20+")
    stat_cols[1].metric(label="Top‑20 admits", value="7")
    stat_cols[2].metric(label="AP 5s", value="30+")


def testimonials_section():
  st.header('What students say')
  TESTIMONIALS = [
    { 'name': 'Maya R.', 'role':'Class of 2024, MIT', 'quote':'Their mentorship shaped my research project which became my application highlight.' },
    { 'name': 'Rohan C.', 'role':'Class of 2023, Stanford', 'quote':'Targeted coaching and relentless practice took my SAT from 1370 to 1550.' },
    { 'name': 'Sara L.', 'role':'AP 5s student', 'quote':'Amazing AP bootcamp — clear structure and lots of practice tests.' },
  ]

  cols = st.columns([1, 1, 1])
  for i, t in enumerate(TESTIMONIALS):
    with cols[i]:
      st.image("https://placehold.co/120x120?text=" + t['name'].split()[0][0], width=72)
      st.subheader(t['name'])
      st.caption(t['role'])
      st.write(t['quote'])


def trust_section():
  st.write("")
  st.subheader("Trusted outcomes & features")
  c1, c2, c3 = st.columns([1, 1, 1])
  c1.write("1500+ SAT improvements")
  c2.write("Top‑20 acceptances")
  c3.write("AP 5s & exam wins")


def next_weekday(start_date, target_weekday):
  """Return the next date at or after start_date that falls on target_weekday (0=Mon..6=Sun)."""
  days_ahead = target_weekday - start_date.weekday()
  if days_ahead <= 0:
    days_ahead += 7
  return start_date + timedelta(days=days_ahead)


def program_detail(program_id: int):
  # find program
  prog = next((p for p in PROGRAMS if p['id'] == program_id), None)
  if not prog:
    st.warning("Program not found")
    return

  st.subheader(prog['title'])
  # If this is AP Bootcamp, show the currently selected AP course (if any)
  if program_id == 3:
    selected_course = st.session_state.get('selected_ap_course')
    if selected_course:
      st.markdown(f"**Selected AP course:** {selected_course}")
    else:
      st.info("No AP course selected. Please choose a course from the Programs listing to see course-specific details.")
  st.write(prog['summary'])
  st.markdown(f"**Price:** {prog['price']}")

  # --- Expanded program-specific details ---
  if program_id == 1:
    st.markdown("### SAT / ACT Math Intensive (Personalized)")
    st.write("We split the math offerings by test and goal: Keshav leads SAT Math, Aditya leads ACT Math & Science.")
    st.write("Key outcomes:")
    st.write("- SAT Math: goal 780–800 via strategy, advanced problem solving, and exam simulation (instructor: Keshav)")
    st.write("- ACT Math & Science: goal 35–36 with focused timing strategies and content mastery (instructor: Aditya)")
    st.write("Format & delivery:")
    st.write("- 1:1 weekly sessions (60–90 minutes), weekly practice sets, and full-length mock tests every 3–4 weeks.")
    st.write("- Personalized error log, topic prioritization, and score-tracking dashboard.")
    st.write("")
    st.write("**Choose which track you want to request more info for:**")
    col_sat, col_act = st.columns([1,1])
    with col_sat:
      if st.button("Request SAT Math info (Keshav)", key=f"contact_sat_{program_id}"):
        st.session_state['page'] = 'Contact'
        st.session_state['contact_prefill'] = "I'm interested in SAT Math prep (goal: 780-800) — please connect me with Keshav Balakrishna."
    with col_act:
      if st.button("Request ACT Math/Science info (Aditya)", key=f"contact_act_{program_id}"):
        st.session_state['page'] = 'Contact'
        st.session_state['contact_prefill'] = "I'm interested in ACT Math & Science prep (goal: 35-36) — please connect me with Aditya Baisakh."

  elif program_id == 2:
    st.markdown("### College Consulting — Application Strategy & Execution")
    st.write("Keshav leads our College Consulting offering — hands-on application strategy, essay coaching, and deadline management.")
    st.write("What we cover:")
    st.write("- Full application timeline & roadmap (school lists, reach/match/safety strategy)")
    st.write("- Essay brainstorming, outline, iterative edits, and mock interview prep")
    st.write("- Supplemental materials: research/project packaging, rec letter strategy, and final review")
    st.write("")
    if st.button("Request College Consulting with Keshav", key=f"contact_consult_{program_id}"):
      st.session_state['page'] = 'Contact'
      st.session_state['contact_prefill'] = "I would like to schedule college consulting with Keshav Balakrishna (application strategy, essays, and timeline). Please contact me."

  elif program_id == 3:
    # AP Bootcamp – course-specific information
    selected_course = st.session_state.get('selected_ap_course')
    st.markdown("### AP Bootcamp — course breakdown & outcomes")
    if selected_course:
      st.write(f"**Course:** {selected_course}")
      # instructor assignment
      instructor = 'Keshav Balakrishna' if selected_course in ['AP Computer Science A', 'AP Calculus AB/BC'] else 'Aditya Baisakh'
      st.write(f"**Instructor:** {instructor}")
      st.write("Typical course features:")
      st.write("- 8–12 week intensive format with weekly lessons, targeted practice, and exam-style unit tests.")
      st.write("- Focus: concept mastery, problem solving under time pressure, and exam strategy. Includes past-paper reviews and mini-projects for CSA.")
      if selected_course == 'AP Computer Science A':
        st.write("AP CSA highlights: coding practice (Java), data structures, OOP design, and performance-focused project work. Hands-on labs and coding challenges.")
      if selected_course.startswith('AP Calculus'):
        st.write("AP Calculus AB/BC highlights: accelerated problem sets, series & parametric focus for BC, AP exam strategy, and free-response practice.")
      st.write("Outcomes: improved conceptual mastery, consistent 5-level performance on AP scoring rubrics, and portfolio-ready projects (where relevant).")
      st.write("Format & scheduling: weekly 60–90 minute sessions, practice tests, and topic-based assignments.")
    else:
      st.info("Choose an AP course from the Programs page to see details; Aditya teaches the non‑CSA/Calc AP classes, Keshav teaches AP CSA and AP Calculus.")
    st.write("Pricing & packages: flexible hourly tutoring or multi-week bootcamps — contact us for custom packages and group rates.")

  c1, c2 = st.columns([1, 1])
  with c1:
    if st.button("Request info about this program", key=f"contact_prog_{program_id}"):
      st.session_state['page'] = 'Contact'
      # If AP Bootcamp, include the selected AP course in the prefill for clarity
      if program_id == 3 and st.session_state.get('selected_ap_course'):
        st.session_state['contact_prefill'] = f"I'm interested in learning more about: {prog['title']} — {st.session_state['selected_ap_course']}. Please contact me."
      else:
        st.session_state['contact_prefill'] = f"I'm interested in learning more about: {prog['title']} — please contact me."
  with c2:
    if st.button("Clear selection", key=f"clear_prog_{program_id}"):
      st.session_state['selected_program'] = None
      # clear AP-specific selection when clearing details
      if program_id == 3:
        st.session_state['selected_ap_course'] = None


def _bookings_path():
  return os.path.join(os.path.dirname(__file__), 'bookings.csv')


def load_bookings():
  path = _bookings_path()
  if not os.path.exists(path):
    return []
  with open(path, newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    return list(reader)


def save_bookings(rows):
  path = _bookings_path()
  if not rows:
    # clear file
    open(path, 'w').close()
    return
  # determine headers (union of keys)
  headers = []
  for r in rows:
    for k in r.keys():
      if k not in headers:
        headers.append(k)
  with open(path, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=headers)
    writer.writeheader()
    for r in rows:
      writer.writerow(r)


def send_confirmation_email(to_email, subject, body):
  smtp_host = os.getenv('SMTP_HOST')
  smtp_port = int(os.getenv('SMTP_PORT') or 0)
  smtp_user = os.getenv('SMTP_USER')
  smtp_pass = os.getenv('SMTP_PASS')
  from_email = os.getenv('FROM_EMAIL') or smtp_user
  if not smtp_host or not smtp_port or not smtp_user or not smtp_pass:
    raise RuntimeError('SMTP credentials not configured in environment')
  import smtplib
  from email.message import EmailMessage
  msg = EmailMessage()
  msg['Subject'] = subject
  msg['From'] = from_email
  msg['To'] = to_email
  msg.set_content(body)

  # connect
  if smtp_port == 465:
    server = smtplib.SMTP_SSL(smtp_host, smtp_port)
  else:
    server = smtplib.SMTP(smtp_host, smtp_port)
    server.starttls()
  server.login(smtp_user, smtp_pass)
  server.send_message(msg)
  server.quit()


def admin_section():
  st.markdown('### Bookings')
  rows = load_bookings()
  if not rows:
    st.info('No bookings yet (bookings.csv is empty).')
    return

  # Provide a quick filter and show bookings
  statuses = sorted({r.get('status', 'pending') for r in rows})
  filter_status = st.selectbox('Filter by status', ['all'] + statuses, index=0)
  display_rows = [r for r in rows if filter_status == 'all' or r.get('status','pending') == filter_status]

  for idx, r in enumerate(display_rows):
    st.markdown('---')
    st.write(f"**#{idx+1} — {r.get('name','')}**")
    st.write(f"Email: {r.get('email','')}")
    st.write(f"Slot: {r.get('slot_label','')} — {r.get('slot_local_start','')} to {r.get('slot_local_end','')}")
    st.write(f"Message: {r.get('message','')}")
    if r.get('event_link'):
      st.markdown(f"Calendar event: [Open]({r.get('event_link')})")
    if r.get('meet_link'):
      st.markdown(f"Meet link: [Join]({r.get('meet_link')})")

    cols = st.columns([1,1,1])
    # create event automatically if libraries/credentials available and no event yet
    if GOOGLE_LIBS_AVAILABLE and not r.get('event_link'):
      if cols[0].button('Create event & Meet', key=f'admin_create_{idx}'):
        try:
          creds_file = os.path.join(os.path.dirname(__file__), 'credentials.json')
          if not os.path.exists(creds_file):
            st.error('credentials.json missing in project root')
          else:
            scopes = ['https://www.googleapis.com/auth/calendar.events']
            flow = InstalledAppFlow.from_client_secrets_file(creds_file, scopes=scopes)
            creds = flow.run_local_server(port=0)
            service = build('calendar', 'v3', credentials=creds)
            # parse start/end from booking
            start = datetime.fromisoformat(r.get('slot_local_start')).astimezone(ZoneInfo('UTC'))
            end = datetime.fromisoformat(r.get('slot_local_end')).astimezone(ZoneInfo('UTC'))
            event = {
              'summary': 'STEMSphere — Free 30-minute info/planning session',
              'description': r.get('message',''),
              'start': {'dateTime': start.isoformat(), 'timeZone':'UTC'},
              'end': {'dateTime': end.isoformat(), 'timeZone':'UTC'},
              'attendees': [{'email': r.get('email','')}, {'email':'info@stemsphere.org'}],
              'conferenceData': { 'createRequest': { 'requestId': f"admin-{datetime.utcnow().timestamp()}" }}
            }
            created_event = service.events().insert(calendarId='primary', body=event, conferenceDataVersion=1).execute()
            meet_link = ''
            if 'conferenceData' in created_event:
              for ep in created_event.get('conferenceData', {}).get('entryPoints', []):
                if ep.get('entryPointType') == 'video':
                  meet_link = ep.get('uri')
            # update row
            r['event_link'] = created_event.get('htmlLink','')
            r['meet_link'] = meet_link
            r['status'] = 'confirmed'
            r['confirmed_utc'] = datetime.utcnow().isoformat()
            save_bookings(rows)
            st.success('Event created and booking updated')
        except Exception as e:
          st.error(f'Failed to create event: {e}')

    # send confirmation email
    smtp_ok = bool(os.getenv('SMTP_HOST') and os.getenv('SMTP_USER') and os.getenv('SMTP_PASS'))
    if smtp_ok:
      if cols[1].button('Send confirmation email', key=f'admin_email_{idx}'):
        try:
          subject = 'STEMSphere — Consultation confirmed'
          meet_text = f"\nJoin the meeting: {r.get('meet_link')}" if r.get('meet_link') else ''
          body = f"Hi {r.get('name')},\n\nYour 30-minute consultation on {r.get('slot_label')} has been scheduled. {meet_text}\n\nThis session is free and is meant as an information/planning session to understand the student's circumstances.\n\n— STEMSphere"
          send_confirmation_email(r.get('email'), subject, body)
          # update rows
          r['email_sent_utc'] = datetime.utcnow().isoformat()
          r['status'] = r.get('status','confirmed')
          save_bookings(rows)
          st.success('Email sent successfully')
        except Exception as e:
          st.error(f'Failed to send email: {e}')
    else:
      if cols[1].button('Mark email sent', key=f'admin_markemail_{idx}'):
        r['email_sent_utc'] = datetime.utcnow().isoformat()
        save_bookings(rows)
        st.success('Marked as email sent')

    if cols[2].button('Mark confirmed', key=f'admin_confirm_{idx}'):
      r['status'] = 'confirmed'
      r['confirmed_utc'] = datetime.utcnow().isoformat()
      save_bookings(rows)
      st.success('Booking marked confirmed')


def programs_section():
  st.header("Our Programs")
  st.write("Search, filter, and learn more about our most popular offerings:")

  query = st.text_input("Search programs by keyword", value='')
  filtered = [p for p in PROGRAMS if query.lower() in (p['title']+p['summary']).lower()]

  # If a program has been selected, show details first
  if st.session_state.get('selected_program'):
    program_detail(st.session_state['selected_program'])

  cols = st.columns([1, 1, 1])
  for i, p in enumerate(filtered):
    c = cols[i % 3]
    with c:
      st.subheader(p['title'])
      st.write(p['summary'])
      st.markdown(f"**Price:** {p['price']}")
      # If this is the AP Bootcamp, show dropdown of offered AP courses
      if p.get('id') == 3 and p.get('courses'):
        # initial value preference: session stored selected_ap_course, or first option
        default_choice = st.session_state.get('selected_ap_course') or p['courses'][0]
        ap_choice = st.selectbox('Which AP course are you interested in?', p['courses'], index=p['courses'].index(default_choice) if default_choice in p['courses'] else 0, key=f"ap_select_{p['id']}")
        # persist the selection
        st.session_state['selected_ap_course'] = ap_choice
      # clicking learn sets a selected_program and persists the AP selection if present
      if st.button(f"Learn more — {p['id']}", key=f"learn_{p['id']}"):
        st.session_state['selected_program'] = p['id']
        # if program is AP Bootcamp, ensure we have a selected_ap_course to show in detail
        if p.get('id') == 3 and st.session_state.get('selected_ap_course') is None:
          # set default
          st.session_state['selected_ap_course'] = p['courses'][0]
        # stay on Programs page
        st.session_state['page'] = 'Programs'


def about_section():
  st.header("About Us")
  col_a, col_b = st.columns([2,1])
  with col_a:
    st.markdown("STEMSphere connects ambitious students with qualified and experienced mentors and a clear path to competitive STEM programs. We focus on measurable outcomes: test scores, research exposure, and application strength.")
    st.markdown("### Coaches & Mentors")
    st.markdown("- Keshav Balakrishna — Co-founder, 1520 SAT, Accepted to multiple top 20 CS schools such as Purdue and UT Austin\n- Aditya Baisakh — Co-founder, 1520 SAT and 34 ACT, Accepted to T20 CS schools such as Georgia Tech and Purdue")
  with col_b:
    st.image(LOGO_URL, width=150)


def contact_section():
  st.header("Contact & Request Consultation")
  st.write("We respond to messages within 48 hours. For urgent inquiries use the email below.")
  st.markdown("**Email:** stemsphere60@gmail.com  —  **Instagram:** @stemsphere  —  **LinkedIn:** STEMSphere")

  left, right = st.columns([1, 1])
  with left:
    st.subheader('Book a short consult')
    st.write('Free 20-minute discovery — find the exact plan for your student.')
    st.write('Or email **info@stemsphere.org**')

  with right:
    tab1, tab2 = st.tabs(["Send message", "Schedule Google Meet (instant / calendar)"])

    with tab1:
      st.markdown('### Connect with us')
      st.write('Prefer to reach out directly? Use one of these channels:')
      st.markdown('- **Email:** [stemsphere60@gmail.com](mailto:stemsphere60@gmail.com)')
      st.markdown('- **LinkedIn:** [STEMSphere](https://linkedin.com/company/stemsphere)')
      st.markdown('- **Instagram:** [@stemsphere](https://instagram.com/stemsphere)')
      st.write('Or schedule a free 30-minute info/planning session on the Schedule tab.')

    with tab2:
      st.write("Quick options — start an instant Google Meet or schedule one on Google Calendar.")
      # Instant Meet
      if st.button('Start a Google Meet now', key='meet_now'):
        st.markdown("[Open an instant Google Meet](https://meet.new){:target='_blank'}", unsafe_allow_html=True)

      st.write('---')
      st.write('Schedule a Meet (we offer free 30-minute info/planning sessions on the weekend — choose one slot below)')
      st.write('Available slots (Central Time):')
      # choose staff for meeting
      staff_choice = st.selectbox('Who would you like to meet with?', ['Keshav Balakrishna', 'Aditya Baisakh'])
      keshav_email = os.getenv('KESHAV_EMAIL') or 'keshav@stemsphere.org'
      aditya_email = os.getenv('ADITYA_EMAIL') or 'aditya@stemsphere.org'
      staff_email = keshav_email if staff_choice.startswith('Keshav') else aditya_email
      slot_options = [
        ('Sat 6:00 PM CST (30 min)', 'sat_18_00'),
        ('Sun 11:00 AM CST (30 min)', 'sun_11_00'),
        ('Sun 3:00 PM CST (30 min)', 'sun_15_00'),
        ('Sun 6:00 PM CST (30 min)', 'sun_18_00'),
      ]
      labels = [s[0] for s in slot_options]
      # If Google credentials and calendar email available, attempt availability check and filter slots
      available_labels = []
      availability_info = {}
      can_check = GOOGLE_LIBS_AVAILABLE and os.path.exists(os.path.join(os.path.dirname(__file__), 'credentials.json')) and staff_email
      for label, key in slot_options:
        # compute next local start/end to check
        if key == 'sat_18_00':
          target_day = 5; hour = 18; minute = 0
        elif key == 'sun_11_00':
          target_day = 6; hour = 11; minute = 0
        elif key == 'sun_15_00':
          target_day = 6; hour = 15; minute = 0
        else:
          target_day = 6; hour = 18; minute = 0
        event_date = next_weekday(date.today(), target_day)
        tz = ZoneInfo('America/Chicago')
        start_local = datetime.combine(event_date, time(hour=hour, minute=minute)).replace(tzinfo=tz)
        end_local = start_local + timedelta(minutes=30)
        if can_check:
          available = check_slot_availability(start_local, end_local, staff_email)
        else:
          available = True
        availability_info[label] = (available, start_local, end_local)
        if available:
          available_labels.append(label)

      if not can_check:
        st.info('Availability check is disabled because Google credentials or staff calendar emails are not provided. All slots are shown by default.')
      if not available_labels:
        st.warning('No available slots were detected for the chosen staff in the upcoming weeks.')

      choice = st.selectbox('Choose a slot', available_labels or labels)
      # map choice back to key
      key_map = {s[0]: s[1] for s in slot_options}
      chosen_key = key_map[choice]

      booking_name = st.text_input('Name for booking (required)', value='')
      booking_email = st.text_input('Your email (optional)', value='')
      booking_msg = st.text_area('Message / context (optional)', value='')

      if st.button('Create Google Calendar event for chosen slot', key='create_slot_gc'):
        # compute next date for the selected slot
        today = date.today()

        if chosen_key == 'sat_18_00':
          target_day = 5; hour = 18; minute = 0
        elif chosen_key == 'sun_11_00':
          target_day = 6; hour = 11; minute = 0
        elif chosen_key == 'sun_15_00':
          target_day = 6; hour = 15; minute = 0
        else: # sun_18_00
          target_day = 6; hour = 18; minute = 0

        event_date = next_weekday(today, target_day)
        # session length fixed at 30 minutes
        # Use timezone-aware datetimes (America/Chicago) so DST is handled correctly
        tz = ZoneInfo('America/Chicago')
        start_dt_local = datetime.combine(event_date, time(hour=hour, minute=minute)).replace(tzinfo=tz)
        end_dt_local = start_dt_local + timedelta(minutes=30)

        # Convert to UTC for Google Calendar
        start_dt_utc = start_dt_local.astimezone(ZoneInfo('UTC'))
        end_dt_utc = end_dt_local.astimezone(ZoneInfo('UTC'))

        start_str = start_dt_utc.strftime('%Y%m%dT%H%M%SZ')
        end_str = end_dt_utc.strftime('%Y%m%dT%H%M%SZ')

        title = urllib.parse.quote('STEMSphere — Free 30-minute info/planning session')
        details_text = f"This is a free 30-minute introductory information/planning session to understand the student's circumstances. Requested by: {booking_name}. {booking_msg or ''}"
        details = urllib.parse.quote(details_text)
        add = urllib.parse.quote('info@stemsphere.org')

        gc_url = f"https://calendar.google.com/calendar/r/eventedit?text={title}&details={details}&dates={start_str}/{end_str}&add={add}"

        # Persist booking locally for record (bookings.csv)
        bookings_file = os.path.join(os.path.dirname(__file__), 'bookings.csv')
        created = not os.path.exists(bookings_file)
        with open(bookings_file, 'a', newline='', encoding='utf-8') as bf:
          bw = csv.writer(bf)
          if created:
            bw.writerow(['created_utc', 'name', 'email', 'slot_label', 'slot_local_start', 'slot_local_end', 'message', 'event_link', 'meet_link'])
          bw.writerow([datetime.utcnow().isoformat(), booking_name, booking_email, choice, start_dt_local.isoformat(), end_dt_local.isoformat(), booking_msg, '', ''])

        st.markdown(f"[Open Google Calendar to create this event (pre-filled)]({gc_url})", unsafe_allow_html=True)
        # Also offer automatic creation if google libs and credentials are available
        if GOOGLE_LIBS_AVAILABLE:
          st.write('Or create the event automatically (requires a local Google OAuth credentials.json)')
          if st.button('Create event & Meet automatically (requires credentials.json)', key='auto_create_gc'):
            try:
              # create event on Google Calendar and request conference data
              creds_file = os.path.join(os.path.dirname(__file__), 'credentials.json')
              token_file = os.path.join(os.path.dirname(__file__), 'token.json')
              if not os.path.exists(creds_file):
                st.error('credentials.json not found in project root. See README for setup steps.')
              else:
                # Run installed app flow to get credentials (stores token.json)
                scopes = ['https://www.googleapis.com/auth/calendar.events']
                flow = InstalledAppFlow.from_client_secrets_file(creds_file, scopes=scopes)
                creds = flow.run_local_server(port=0)
                service = build('calendar', 'v3', credentials=creds)

                # prepare event body with conference creation request
                event = {
                  'summary': 'STEMSphere — Free 30-minute info/planning session',
                  'description': details_text,
                  'start': { 'dateTime': start_dt_utc.isoformat(), 'timeZone': 'UTC' },
                  'end': { 'dateTime': end_dt_utc.isoformat(), 'timeZone': 'UTC' },
                  'attendees': [{'email': 'info@stemsphere.org'}],
                  'conferenceData': { 'createRequest': { 'requestId': f"stemsphere-{datetime.utcnow().timestamp()}" } }
                }

                created_event = service.events().insert(calendarId='primary', body=event, conferenceDataVersion=1).execute()
                # extract meet link
                meet_link = None
                if 'conferenceData' in created_event:
                  conf = created_event.get('conferenceData', {})
                  entry_points = conf.get('entryPoints', [])
                  for ep in entry_points:
                    if ep.get('entryPointType') == 'video':
                      meet_link = ep.get('uri')
                # Save to bookings.csv also the created event link if present
                with open(bookings_file, 'a', newline='', encoding='utf-8') as bf:
                  bw = csv.writer(bf)
                  bw.writerow([datetime.utcnow().isoformat(), booking_name, booking_email, choice, start_dt_local.isoformat(), end_dt_local.isoformat(), booking_msg, created_event.get('htmlLink', ''), meet_link or ''])

                st.success('Event created!')
                if created_event.get('htmlLink'):
                  st.markdown(f"[Open event in Google Calendar]({created_event.get('htmlLink')})", unsafe_allow_html=True)
                if meet_link:
                  st.markdown(f"**Google Meet link:** [Join meeting]({meet_link})", unsafe_allow_html=True)
            except Exception as e:
              st.error(f'Unable to create event automatically: {e}')
      
  # --- helper to check staff availability for slots (requires credentials and staff calendar emails)
def check_slot_availability(slot_start_local, slot_end_local, staff_email):
  """Return True if staff_email is free during the local start/end (slot_start_local is timezone-aware)."""
  if not GOOGLE_LIBS_AVAILABLE:
    return None  # not available for checks
  creds_file = os.path.join(os.path.dirname(__file__), 'credentials.json')
  if not os.path.exists(creds_file):
    return None
  try:
    scopes = ['https://www.googleapis.com/auth/calendar.readonly']
    flow = InstalledAppFlow.from_client_secrets_file(creds_file, scopes=scopes)
    creds = flow.run_local_server(port=0)
    service = build('calendar', 'v3', credentials=creds)
    body = {
      "timeMin": slot_start_local.astimezone(ZoneInfo('UTC')).isoformat(),
      "timeMax": slot_end_local.astimezone(ZoneInfo('UTC')).isoformat(),
      "items": [{"id": staff_email}]
    }
    resp = service.freebusy().query(body=body).execute()
    busy = resp.get('calendars', {}).get(staff_email, {}).get('busy', [])
    return len(busy) == 0
  except Exception:
    return None
    # form end


def faq_section():
  st.header("FAQ")
  st.markdown("**Q:** How long are your programs? — **A:** Typically 8–12 weeks with flexible plans.")


def footer():
  st.write(f"© {datetime.now().year} STEMSphere — Privacy • Terms • Built with ❤️ for students")


# ---------- Page routing ----------
PAGES = ["Home", "Programs", "About", "Contact", "FAQ", "Legal"]
# Routing: only use header navigation (top of page). Avoid sidebar routing to prevent widget-key conflicts.
page = st.session_state.get('page', 'Home')

# Clear selected program unless we're on the Programs page (prevents detail view showing on other pages)
if page != 'Programs':
  st.session_state['selected_program'] = None
  # also clear AP course selection when leaving Programs
  st.session_state['selected_ap_course'] = None

header()
hero()

if page == "Home":
  trust_section()
  programs_section()
  testimonials_section()
elif page == "Programs":
  trust_section()
  programs_section()
  testimonials_section()
  st.markdown("---")
  st.markdown("Interested in a custom plan? Use the contact form to request a consultation.")
elif page == "About":
  about_section()
elif page == "Contact":
  contact_section()
elif page == "Admin":
  # Admin page requires correct password in an env var
  admin_password = os.getenv('ADMIN_PASSWORD')
  st.header('Admin — Bookings & Scheduling')
  if not admin_password:
    st.warning('Admin disabled: set ADMIN_PASSWORD in environment to enable admin UI.')
  else:
    pw = st.text_input('Enter admin password', type='password')
    if pw != admin_password:
      st.info('Enter password to unlock admin tools')
    else:
      # Admin unlocked
      st.success('Admin unlocked')
      admin_section()
elif page == "FAQ":
  faq_section()
elif page == "Legal":
  st.header("Legal & Policy")
  st.markdown("Privacy Policy | Terms of Use | Accessibility Statement")

st.markdown("---")
footer()

