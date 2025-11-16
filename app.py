import streamlit as st

st.markdown("""
<link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.0/css/bootstrap.min.css">
<nav class="navbar navbar-expand-lg navbar-light bg-light sticky-top">
  <a class="navbar-brand" href="#">STEMSphere</a>
  <div class="collapse navbar-collapse">
    <ul class="navbar-nav mr-auto">
      <li class="nav-item"><a class="nav-link" href="#home">Home</a></li>
      <li class="nav-item"><a class="nav-link" href="#about">About</a></li>
      <li class="nav-item"><a class="nav-link" href="#programs">Our Programs</a></li>
      <li class="nav-item"><a class="nav-link" href="#contact">Contact</a></li>
      <li class="nav-item"><a class="nav-link" href="#faq">FAQ</a></li>
    </ul>
  </div>
</nav>
""", unsafe_allow_html=True)

page = st.sidebar.radio("Navigate", ["Home", "About Us", "Our Programs", "Contact", "FAQ", "Legal/Policy"])

if page == "Home":
    st.header("Welcome to STEMSphere")
    st.subheader("Empowering Students for Elite Success")
    st.markdown("Brief summary of mission, ongoing projects, core values, etc.")
    cols = st.columns([1,1,1])
    cols[0].markdown("**SAT/ACT High Scores:** 20+ students with 1500+ SAT or 34+ ACT")
    cols[1].markdown("**T20 Acceptances:** 7 students admitted to Top-20 colleges")
    cols[2].markdown("**AP 5's:** 30+ AP exams scored 5s")
    st.markdown("---")

elif page == "About Us":
    st.header("About STEMSphere")
    st.markdown("""
    <div style="display:flex;flex-direction:row;justify-content:space-between;align-items:center;">
      <div style="margin-right:40px">
        <img src='URL_to_Keshav_image' width='100'>
        <p><strong>Keshav Balakrishna</strong><br>Co-Founder</p>
      </div>
      <div>
        <img src='URL_to_Aditya_image' width='100'>
        <p><strong>Aditya Baisakh</strong><br>Co-Founder</p>
      </div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("Our mission is to democratize elite college and test prep access... [flowing paragraph about backgrounds and achievements]")

elif page == "Our Programs":
    st.header("Academic & College Consulting Programs")
    st.write("Search programs and resources:")
    st.markdown("List of all programs, brief overview, total costs...")

elif page == "Contact":
    st.header("Contact Us")
    st.markdown("""
    - Email: info@stemsphere.org
    - LinkedIn: [STEMSphere](https://linkedin.com/company/stemsphere)
    - Instagram: @stemsphere
    """)

elif page == "FAQ":
    st.header("FAQ")
    st.markdown("Frequently asked questions go here.")

elif page == "Legal/Policy":
    st.header("Legal & Policy")
    st.markdown("Privacy Policy | Terms of Use | Accessibility Statement")

st.markdown("""
<style>
@media (max-width: 600px) {
  .navbar {font-size:14px;}
  .columns {flex-direction:column;}
  img {width:60%;}
}
</style>
""", unsafe_allow_html=True)
