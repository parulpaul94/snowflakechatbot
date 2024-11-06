import os
import io
import pandas as pd
import streamlit as st
import snowflake.connector
import base64
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader
from gpt import OpenAIService  

CONFIG_FILENAME = 'config.yaml'

# Function to read prompt files
def read_prompt_file(fname):
    with open(fname, "r", encoding='utf-8') as f:
        return f.read()

# Function to get the base64 encoded version of the image
def get_base64_of_bin_file(bin_file):
    with open(bin_file, 'rb') as f:
        data = f.read()
    return base64.b64encode(data).decode()

# Load configuration for authentication
with open(CONFIG_FILENAME) as file:
    config = yaml.load(file, Loader=SafeLoader)

# Set wide layout for Streamlit app
st.set_page_config(layout="wide")

# Custom CSS for styling
st.markdown(
    """
    <style>
        body {
            background-image: url('your_background_image_url_here'); /* Set your background image URL */
            background-size: cover;
            background-repeat: no-repeat;
            background-attachment: fixed;
        }
        .sidebar .sidebar-content {
            background-color: rgba(0, 0, 139, 0.7);
        }
        .stTextInput, .stTextArea {
            background-color: rgba(211, 211, 211, 0.9);
            color: black;
            border-radius: 15px;
            border: 2px solid #00bcd4;
            margin: 10px 0;
            padding: 10px;
        }
        .stButton button {
            background-color: #00bcd4;
            color: #ffffff;
            border: 2px solid #0097a7;
            border-radius: 15px;
            margin: 10px 0;
        }
        .stButton button:hover {
            background-color: #0097a7;
        }
        h1, h2, h3, h4, h5, h6 {
            color: #006064;
        }
        .logo {
            text-align: center;
        }
        .logo img {
            height: 100px;
            width: auto;
        }
        [title="Show password text"] {
            display: none; /* Hide password text */
        }
    </style>
    """,
    unsafe_allow_html=True,
)

st.sidebar.markdown(
    """
    <div class="logo">
        <img src="data:image/png;base64,{0}" alt="Logo" style="height: 100px; width: auto;"/>
    </div>
    """.format(get_base64_of_bin_file('omnia-logo.png')), 
    unsafe_allow_html=True
)

# Authentication Setup
authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days']
)

@st.cache_resource
class SnowflakeDB:
    def __init__(self) -> None:
        self.conn = snowflake.connector.connect(
            user=os.getenv("SNOWFLAKE_USER", "default_user"),
            password=os.getenv("SNOWFLAKE_PASSWORD", "default_password"),
            account=os.getenv("SNOWFLAKE_ACCOUNT", "default_account"),
            warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "default_warehouse"),
            database=os.getenv("SNOWFLAKE_DATABASE", "default_database"),
            schema=os.getenv("SNOWFLAKE_SCHEMA", "default_schema")
        )
        self.cursor = self.conn.cursor()

@st.cache_data
def query(_conn, query_text):
    try:
        return pd.read_sql(query_text, _conn)
    except Exception as e:
        st.warning("Error in query")
        st.error(e)
        return None

@st.cache_data
def ask(prompt):
    gpt = OpenAIService()
    response = gpt.prompt(prompt)
    return response["choices"][0]["message"]["content"] if response else None

def get_tables_schema(_conn):
    table_schemas = ""
    df = query(_conn, "SHOW TABLES")
    if df is not None:
        for table in df["name"]:
            t = f"{os.getenv('SNOWFLAKE_DATABASE')}.{os.getenv('SNOWFLAKE_SCHEMA')}.{table}"
            ddl_query = f"SELECT GET_DDL('table', '{t}');"
            ddl = query(_conn, ddl_query)
            schema = f"\n{ddl.iloc[0, 0]}\n" if ddl is not None and not ddl.empty else "No schema available."
            table_schemas += f"\n{table}\n{schema}\n"
    return table_schemas

def sanitize_input(input_string):
    return input_string.encode('utf-8', 'ignore').decode('utf-8')

def validate_sql(sql):
    restricted_keywords = ["DROP", "ALTER", "TRUNCATE", "UPDATE", "REMOVE"]
    for keyword in restricted_keywords:
        if keyword in sql.upper():
            return False, keyword
    return True, None

# Main Application Logic
def main():
    # Initialize session state variables
    if 'authentication_status' not in st.session_state:
        st.session_state.authentication_status = None
    if 'openai_key_entered' not in st.session_state:
        st.session_state.openai_key_entered = False
    if 'question' not in st.session_state:
        st.session_state.question = ""

    # Registration Expander
    register_expander = st.sidebar.expander('Register', expanded=True)
    with register_expander:
        with st.form(key="register_form"):
            new_username = st.text_input("New Username")
            new_password = st.text_input("New Password", type="password")
            new_name = st.text_input("Name", placeholder="Enter your name")
            new_role = st.text_input("Role", placeholder="User role")
            submitted = st.form_submit_button("Register")

            if submitted:
                if new_username and new_password and new_name and new_role:
                    try:
                        authenticator.register_user(
                            name=new_name,
                            username=new_username,
                            password=new_password,
                            role=new_role,
                            location='sidebar'
                        )
                        config['credentials']['usernames'][new_username] = {
                            'name': new_name,
                            'password': new_password,
                            'role': new_role,
                        }
                        with open(CONFIG_FILENAME, 'w') as file:
                            yaml.dump(config, file)
                        st.success(f"User '{new_username}' registered successfully!")
                    except Exception as e:
                        st.error(f"Error during registration: {e}")
                else:
                    st.error("Please fill in all fields.")

    # Login Expander
    login_expander = st.sidebar.expander('Login')
    with login_expander:
        if st.session_state.authentication_status is None:
            username = st.text_input("Username", placeholder="Enter your username")
            password = st.text_input("Password", type="password", placeholder="Enter your password")
            if st.button("Login"):
                login_result = authenticator.login(username=username, password=password)
                if login_result:
                    st.session_state.authentication_status = True
                    st.session_state.name = username
                    st.experimental_rerun()
                else:
                    st.error("Username/password is incorrect")

    # Main application logic after login
    if st.session_state.authentication_status:
        st.success(f'Welcome *{st.session_state.name}*!')
        display_credentials_form()

        # Display Snowflake integration section after credentials are submitted
        if st.session_state.openai_key_entered:
            snowflake_integration()

def display_credentials_form():
    st.sidebar.subheader("Snowflake Credentials")
    
    if st.session_state.openai_key_entered is False:
        # Default Snowflake credentials
        st.session_state.user = os.getenv("SNOWFLAKE_USER", "Omni")
        st.session_state.password = os.getenv("SNOWFLAKE_PASSWORD", "Omni@123")
        st.session_state.account = os.getenv("SNOWFLAKE_ACCOUNT", "yz71246.central-india.azure")
        st.session_state.warehouse = os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH")
        st.session_state.schema = os.getenv("SNOWFLAKE_SCHEMA", "PUBLIC")
        st.session_state.database = os.getenv("SNOWFLAKE_DATABASE", "DEMO_DB")

    # OpenAI API key input
    with st.sidebar.form(key="openai_key_form"):
        openai_api_key = st.text_input("OpenAI API Key", type="password")
        submitted = st.form_submit_button("Submit Key")

        if submitted and openai_api_key:
            st.session_state.openai_api_key = openai_api_key
            st.session_state.openai_key_entered = True
            st.success("OpenAI API Key submitted successfully!")

def snowflake_integration():
    if st.session_state.openai_key_entered:
        st.subheader("Query Snowflake")
        conn = SnowflakeDB()
        
        sql_query = st.text_area("SQL Query", height=150)
        if st.button("Execute Query"):
            valid, keyword = validate_sql(sql_query)
            if valid:
                result_df = query(conn.conn, sql_query)
                if result_df is not None and not result_df.empty:
                    st.dataframe(result_df)
                else:
                    st.warning("No results returned.")
            else:
                st.error(f"Query contains restricted keyword: {keyword}")

        st.subheader("AI Question Answering")
        question = st.text_area("Ask a question to AI")
        if st.button("Get Answer"):
            if question:
                answer = ask(question)
                st.write(answer)
            else:
                st.error("Please enter a question.")

# Run the main application
if __name__ == "__main__":
    main()
