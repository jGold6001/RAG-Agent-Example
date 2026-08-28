import api_utils
import streamlit as st
from auth_component import auth_bridge
from chat_components import authenticated_user_chat_interface_component, unauthenticated_user_chat_interface_component
from state_management import Page, authenticate_user


def home_page():
    st.title("💬 AI-Powered Chatbot")
    if not st.session_state["user"].is_authenticated:
        st.markdown(
            """
            Welcome! This intelligent assistant uses advanced Retrieval-Augmented Generation (RAG) to help you find answers and understand your documents.

            ### ✨ Key Features for Logged-in Users:
            - Ask questions and receive smart, context-aware answers.
            - Upload your own documents for tailored assistance.
            - Use tavily search for general knowledge questions.
            - Enjoy **chat memory** to remember and recall previous conversations.
            """
        )
        st.subheader("💡 What would you like to ask?", divider="rainbow")
        unauthenticated_user_chat_interface_component()
    else:
        st.subheader("💡 What would you like to ask?", divider="rainbow")
        authenticated_user_chat_interface_component()


def login_page():
    st.subheader("🔐 Login", divider="rainbow")
    with st.form("login_form"):
        email = st.text_input("Email *")
        password = st.text_input("Password *", type="password")
        submitted = st.form_submit_button("Login")

    back_to_home_component()

    if submitted:
        st.session_state["pending_login"] = {"email": email, "password": password}
        st.session_state["login_seq"] = st.session_state.get("login_seq", 0) + 1

    if pending_login := st.session_state.get("pending_login"):
        with st.spinner("Logging in..."):
            # Login must happen as a browser fetch, not a server-side request:
            # only the browser can receive/store the HttpOnly refresh cookie
            # the backend sets on a successful login.
            result = auth_bridge(action="login", payload=pending_login, key=f"login_{st.session_state['login_seq']}")
        if result is None:
            st.stop()

        st.session_state["pending_login"] = None
        body = result.get("body") or {}
        if result.get("ok"):
            st.success(body.get("message", "Login successful"))
            st.session_state["page"] = Page.HOME
            authenticate_user(body)
            st.rerun()
        else:
            st.error(body.get("detail", "Login failed. Please try again."))


def register_page():
    st.subheader("✍ Register", divider="rainbow")
    with st.form("register_form"):
        col1, col2 = st.columns(2)
        email = col1.text_input("Email *")
        username = col1.text_input("Username *", max_chars=16)
        password = col1.text_input("Password *", type="password", max_chars=32)
        first_name = col2.text_input("First Name", max_chars=50)
        last_name = col2.text_input("Last Name", max_chars=50)

        submitted = st.form_submit_button("Register")

    back_to_home_component()

    if submitted:
        register_data = {
            "email": email,
            "username": username,
            "password": password,
            "first_name": first_name,
            "last_name": last_name,
        }
        with st.spinner("Registering..."):
            register_response = api_utils.register_user(register_data)
            if message := register_response.get("message"):
                st.success(message)
                st.session_state["page"] = Page.LOGIN
                st.rerun()
            else:
                st.error(register_response.get("detail", "Registration failed. Please try again."))


def back_to_home_component():
    if st.button("⬅️ Back to Home", type="tertiary"):
        st.session_state["page"] = Page.HOME
        st.rerun()
