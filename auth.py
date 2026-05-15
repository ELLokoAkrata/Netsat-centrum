import os
import streamlit as st
import streamlit_authenticator as stauth

_CREDS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.yaml")

def require_login():
    """Muestra login en el sidebar y detiene la app si no está autenticado."""
    authenticator = stauth.Authenticate(credentials=_CREDS_PATH)

    authenticator.login(location="sidebar")

    status = st.session_state.get("authentication_status")

    if status is True:
        with st.sidebar:
            st.markdown(f"👤 **{st.session_state['name']}**")
            st.divider()
            with st.expander("🔑 Cambiar contraseña"):
                try:
                    if authenticator.reset_password(st.session_state["username"], location="main"):
                        st.success("Contraseña actualizada.")
                except Exception as e:
                    st.error(str(e))
            st.divider()
            authenticator.logout("Cerrar sesión")
        return authenticator

    if status is False:
        st.sidebar.error("Usuario o contraseña incorrectos.")

    st.stop()
