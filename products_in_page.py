import streamlit as st
import pandas as pd
import requests
import hashlib
import time
from datetime import datetime, timedelta


st.title('Get Products in a Page')

# Initialize session keys
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "secret_valid_until" not in st.session_state:
    st.session_state.secret_valid_until = None

# Expire the session after 30 minutes
if st.session_state.secret_valid_until:
    if datetime.utcnow() > st.session_state.secret_valid_until:
        st.session_state.authenticated = False
        st.session_state.secret_valid_until = None

# Show secret input only if not authenticated
if not st.session_state.authenticated:
    user_secret = st.text_input("🔐 Enter The Secret", type="password")
    if user_secret:
        if user_secret == st.secrets["app"]["secret"]:
            st.session_state.authenticated = True
            st.session_state.secret_valid_until = datetime.utcnow() + timedelta(minutes=90)
            
            st.success("✅ Secret is correct!")
            time.sleep(2)  # Short delay to show message
            st.rerun()
        else:
            st.error("❌ Secret is wrong!")
            st.info("Enter secret to begin.")

def compute_query_hash(tenants, queries):
    combined = ",".join(tenants) + "|" + "|".join(queries)
    return hashlib.md5(combined.encode("utf-8")).hexdigest()

# Flatten function for attributes
def flatten_hit(hit, tenant):
    flat = {}

    # Add top-level fields
    flat["tenant"] = tenant
    flat["manufacturerSku"] = hit.get("manufacturerSku")
    flat["title"] = hit.get("title")
    flat["productType"] = hit.get("productType")
    flat["promotionType"] = hit.get("promotionType")

    price = hit.get("price", {})
    flat["price.grossAmount"] = price.get("grossAmount")
    flat["price.currencyCode"] = price.get("currencyCode")
    
    # Pull attributes.* into flat keys
    attributes = hit.get("attributes", [{}])[0]  # It’s a list of one dict
    for k, v in attributes.items():
        key = f"attributes.{k}"
        if isinstance(v, list):
            flat[key] = ", ".join(map(str, v))
        else:
            flat[key] = v

    return flat

# Construct the initial request body
def make_body(filter_query, page, tenant):
    tenant = tenant.replace("_", "-").lower()
    return [{
        "indexName": st.secrets["api"][tenant],
        "params": {
            "attributesToHighlight": [],
            "attributesToRetrieve": [
                "title",
                "productId",
                "productType",
                "manufacturerSku",
                "price",
                "discountBadge.text",
                "hasPriceRange",
                "promotionType",
                "attributes"
            ],
            "attributesToSnippet": [],
            "facets": [
                "attributes.*",
                "dynamicAttributes"
            ],
            "filters": filter_query,
            "ruleContexts": [
                "d48wi",
                "default"
            ],
            "hitsPerPage": 1000,
            "page": page,
            "userToken": st.secrets["api"]["token"]
        },
    }]
    
if st.session_state.authenticated:
    options = ["JS_DE", "JS_AT", "MD_DE", "MD_AT", "MD_CH"]

    st.subheader("🔎 Enter Your Filter Queries")
    st.info("**You can get your queries by navigation to the page you want, REFRESH, and paste this in the console**: \n\
    Evelin.data['product-listing-fragment'].rootComponentProps.algoliaConfig\
    .serverState.initialResults['product-list-1'].state.filters")

    # Initialize state once
    if "filter_queries" not in st.session_state:
        st.session_state.filter_queries = []

    if "new_filter_input" not in st.session_state:
        st.session_state.new_filter_input = ""

    if "tenants" not in st.session_state:
        st.session_state.tenants = []

    # User selects tenants
    tenants = st.multiselect("Tenant", options, default=st.session_state.tenants)
    st.session_state.tenants = tenants  # persist selection

    # Input area for a new filter
    st.warning("⚠️ Each query can return at most 1,000 results. Add multiple queries to fetch more.")
    st.session_state.new_filter_input = st.text_area("Add Filter", value=st.session_state.new_filter_input)

    # Button to confirm filter addition

    if st.button("➕ Add This Filter", key="add_filter"):
        if st.session_state.new_filter_input.strip():
            st.session_state.filter_queries.append(st.session_state.new_filter_input.strip())
            st.session_state.new_filter_input = ""  # clear input
        else:
            st.warning("⚠️ Filter cannot be empty.")

    # Show existing filters with delete buttons
    if st.session_state.filter_queries:
        st.subheader("📦 Current Filter Queries")

        # Create a column layout to align delete buttons
        for i, f in enumerate(st.session_state.filter_queries):
            col1, col2 = st.columns([8, 1])
            with col1:
                st.code(f, language="sql")
            with col2:
                if st.button("❌", key=f"delete_{i}"):
                    st.session_state.filter_queries.pop(i)
                    st.rerun()
    

    if tenants and st.session_state.filter_queries:
        current_hash = compute_query_hash(tenants, st.session_state.filter_queries)

        if "last_query_hash" not in st.session_state:
            st.session_state.last_query_hash = None

        if st.button("🚀 Fetch Your Products"):
            if current_hash == st.session_state.last_query_hash:
                st.info("🔁 No changes in queries or tenants — skipping request.")
            else:
                st.session_state.last_query_hash = current_hash
                headers = {
                    "X-Algolia-Application-Id": st.secrets["api"]["app-id"],
                    "X-Algolia-API-Key": st.secrets["api"]["key"],
                    "Content-Type": "application/json"
                }
                api_url = st.secrets["api"]["url"]
                all_results = []

                for i, query in enumerate(st.session_state.filter_queries):
                    query = query.strip().removeprefix('"').removesuffix('" = $2').removesuffix('" = $1') \
                            + " AND inPreview:false AND isTestProduct:false AND isSellable:true"

                    try:
                        for tenant in tenants:
                            response = requests.post(api_url, json=make_body(query, 0, tenant), headers=headers)
                            response.raise_for_status()
                            data = response.json()
                            results = data.get("results", [])[0]
                            nb_pages = results.get("nbPages", 0)
                            total_products = results.get("nbHits", 0)
                            
                            if total_products > 1000:
                                st.success(f"✅ Query {i+1}: Found {total_products} products for {tenant}. ⚠️ This app will only return the first 1000.")
                            else:
                                st.success(f"✅ Query {i+1}: Found {total_products} products for {tenant}.")

                            # Collect data from first response
                            hits = results.get("hits", []) 
                            all_results.extend([flatten_hit(hit, tenant) for hit in hits])

                            # Loop through remaining pages
                            for page in range(1, nb_pages):
                                with st.spinner(f"Fetching page {page} of {nb_pages}..."):
                                    resp = requests.post(api_url, json=make_body(query, page, tenant), headers=headers)
                                    resp.raise_for_status()
                                    results = data.get("results", [])[0]
                                    hits = results.get("hits", []) 
                                    all_results.extend([flatten_hit(hit, tenant) for hit in hits])

                        # Convert to DataFrame
                        df = pd.DataFrame(all_results)
                        df = df.drop_duplicates()
                        st.session_state.last_results_df = df


                    except Exception as e:
                        st.error(f"❌ Error: {str(e)}")

        if "last_results_df" in st.session_state:
            st.subheader("📊 Results Table")
            st.dataframe(st.session_state.last_results_df)

            csv = st.session_state.last_results_df.to_csv(index=False)
            csv_with_bom = '\ufeff' + csv 
            csv_bytes = csv_with_bom.encode('utf-8')
            st.download_button("⬇️ Download CSV", csv_bytes, "results.csv", "text/csv")
    else:
        st.info("Select tenants and add at least one filter to continue.")