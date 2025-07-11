import streamlit as st
import requests
import json
from datetime import datetime
import logging
import os
import pickle

if "trigger_apply" not in st.session_state:
    st.session_state["trigger_apply"] = False

# --- Configuration ---
CACHE_DIR = ".canvas_cache"
TERMS_CACHE_FILE = os.path.join(CACHE_DIR, "terms.pkl")
COURSES_CACHE_FILE_PREFIX = os.path.join(CACHE_DIR, "courses_term_")
CACHE_TTL_HOURS = 24
COURSE_DISPLAY_LIMIT = 5

# --- Streamlit UI Configuration ---
st.set_page_config(layout="wide", page_title="Canvas Course Manager")
st.title("Canvas Course Management Tool")
st.markdown("Manage and reset Canvas course participation settings.")

# --- Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Session State Initialization ---
INITIAL_SESSION_STATE = {
    'course_selections': {},
    'select_all_courses': False,
    'cached_enrollment_counts': {},
    'fetched_terms': [],
    'fetched_courses_by_term': {},
    'selected_term_id': None,
    'current_display_count': COURSE_DISPLAY_LIMIT,
    'data_loaded_and_terms_fetched': False,
    'courses_search_triggered_for_term': False,
    'last_api_token_used': "",
    'last_account_id_used': "",
    'current_selected_term_name': "--- Select a Term ---",
    'last_filtered_courses_cache': [],
    'last_filtered_term_id': None,
    'show_filtering_debug_info': False,
    'app_needs_reset': False,
    'credentials_collapsed': False,
    'courses_collapsed': False,
    'searched_course': None
}
for key, default_value in INITIAL_SESSION_STATE.items():
    if key not in st.session_state:
        st.session_state[key] = default_value

# --- API Helpers ---
def _paginated_get_from_api(url: str, headers: dict) -> list[dict]:
    all_data = []
    current_url = url
    while current_url:
        resp = requests.get(current_url, headers=headers)
        if resp.status_code != 200:
            break
        data = resp.json()
        all_data.extend(data.get('enrollment_terms', data) if isinstance(data, dict) else data)
        links = resp.headers.get('Link', '').split(',')
        current_url = next((l.split(';')[0].strip('<>') for l in links if 'rel="next"' in l), None)
    return all_data

def get_enrollment_count(course_id: str, base_url: str, headers: dict) -> int:
    url = f"{base_url}/api/v1/courses/{course_id}/enrollments?type[]=StudentEnrollment&state[]=active"
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        return len(resp.json())
    return 0

# --- File-Based Cache ---
def _load_from_file_cache(filepath: str):
    if os.path.exists(filepath):
        with open(filepath, 'rb') as f:
            data, timestamp = pickle.load(f)
        if (datetime.now() - timestamp).total_seconds() / 3600 < CACHE_TTL_HOURS:
            return data, timestamp
    return None, None

def _save_to_file_cache(filepath: str, data: list[dict]):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(filepath, 'wb') as f:
        pickle.dump((data, datetime.now()), f)

# --- Step 1: Credentials & Term Selection ---
with st.expander("🔐 Step 1: Canvas Credentials & Term Selection", expanded=not st.session_state.credentials_collapsed):
    st.header("Canvas Credentials")
    canvas_domain = st.text_input("Canvas Domain", placeholder="yourdomain.instructure.com")
    api_token = st.text_input("Canvas API Token", type="password")
    account_id = st.text_input("Canvas Account ID", placeholder="1")

    base_url = f"https://{canvas_domain}"
    headers = {"Authorization": f"Bearer {api_token}"}

    # --- Course ID Quick Search (BEFORE loading terms) ---
    st.subheader("🔎 Quick Course ID Search")
    course_id_search = st.text_input("Search by Course ID", placeholder="e.g., 12345")
    if canvas_domain and api_token and course_id_search:
        url = f"{base_url}/api/v1/courses/{course_id_search.strip()}"
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            course = resp.json()
            st.session_state['searched_course'] = course

            st.markdown(f"### 📘 {course['name']} (ID: {course['id']})")
            st.markdown(f"- **Start Date:** {course.get('start_at', 'None')}")
            st.markdown(f"- **End Date:** {course.get('end_at', 'None')}")
            st.markdown(f"- [Open in Canvas](https://{canvas_domain}/courses/{course['id']})")

            mode = st.radio("Participation Mode", ["Term Driven", "Date Driven"], key="search_mode")
            start_date = None
            end_date = None

            if mode == "Date Driven":
                start_date = st.date_input("Start Date", key="search_start")
                if st.checkbox("No End Date", key="search_no_end"):
                    end_date = None
                else:
                    end_date = st.date_input("End Date", key="search_end")

            if st.button("Apply Settings", key="search_apply"):
                payload = {
                    "course": {
                        "start_at": f"{start_date}T00:00:00Z" if start_date and mode == "Date Driven" else None,
                        "end_at": f"{end_date}T23:59:59Z" if end_date and mode == "Date Driven" else None,
                        "restrict_enrollments_to_course_dates": mode == "Date Driven"
                    },
                    "override_sis_stickiness": True
                }
                update_url = f"{base_url}/api/v1/courses/{course['id']}"
                update_resp = requests.put(update_url, headers=headers, json=payload)
                if update_resp.status_code == 200:
                    st.success("✅ Course updated successfully.")
                else:
                    st.error("❌ Failed to update course.")
        else:
            st.warning("Course not found or access denied.")

    if canvas_domain and api_token and account_id:
        if st.button("🚀 Load Canvas Terms"):
            try:
                url = f"{base_url}/api/v1/accounts/{account_id}/terms?per_page=100"
                terms = _paginated_get_from_api(url, headers)
                if not terms:
                    st.error("No terms returned from Canvas. Check credentials and account ID.")
                else:
                    _save_to_file_cache(TERMS_CACHE_FILE, terms)
                    st.session_state.fetched_terms = terms
                    st.session_state.data_loaded_and_terms_fetched = True
                    st.session_state.credentials_collapsed = True
                    st.rerun()
            except Exception as e:
                st.error(f"Error loading Canvas terms: {e}")

# --- The rest of your term logic continues here as before (unchanged) ---
