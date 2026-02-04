import streamlit as st
import pandas as pd
import utils

st.set_page_config(initial_sidebar_state="collapsed")

st.markdown("# LEGO Sets")

st.markdown("This app will help you find which models are accessible with the pieces you already have in your collection.")
st.markdown("For instructions on how to use, open the sidebar on the left.")

with st.sidebar:
    st.markdown("""
    ## How to use
    1. Select the **models you own** from the list. (You can choose **multiple models**)
    2. The app will calculate the **compatibility** of all other models in the dataset with your collection.
        - **Compatibility** is defined as the percentage of pieces required by a model that you already have in your collection.
    3. In the dropdown menu, choose a model from the compatibility list and you will see which pieces you are **missing** to complete that model.
        - Sometimes the pieces you are missing are just decorative, or you can substitute the piece with another one you have.
    """)

models_df = pd.read_csv("lego_sets.csv")
# models_info_df = pd.read_csv("lego_model_info.csv")
# models_df = models_df.merge(models_info_df[['Model', 'Name']], on='Model', how='left')
piece_info_df = pd.read_csv("lego_pieces.csv")
models_df = models_df.merge(piece_info_df, on='Item No', how='left')
models_df['Color'] = models_df.apply(lambda row: row['Description'].replace(row['Name'], '').strip() if row['IsPart'] and row['Name'] != '?' else '', axis=1)
models_df = models_df.drop(columns=['Description'])

# ========== Fetch my models ==========

models_info_df = pd.read_csv("lego_model_info.csv")
available_models = models_info_df[['Model', 'Name']].drop_duplicates().set_index('Model')['Name'].to_dict()

selected_options = st.multiselect(
    "1. Select your models:",
    options=[f"{model} ({name})" for model, name in available_models.items()],
    default=[]
)

my_models = [int(option.split(" ")[0]) for option in selected_options]

@st.cache_data
def calculate_compatibility(models_df, my_models):
    finder = utils.LegoModelSubsetProcessor(models_df)
    my_df = finder.get_bulk_pieces(my_models[:])
    compatibility_values = {}
    compatibility_missing = {}
    compatibility_dfs = {}
    for model in models_df['Model'].unique():
        compatibility_df = finder.compatibility(my_df, model)
        compatibility_value = finder.get_compatibility(compatibility_df)
        compatibility_values[model] = compatibility_value['percentage']
        compatibility_missing[model] = compatibility_value['missing']
        compatibility_dfs[model] = compatibility_df
    # Convert dict to DataFrame for display
    compatibility_df = pd.DataFrame(list(compatibility_values.items()), columns=['Model', 'Compatibility'])
    compatibility_df['Missing pieces'] = compatibility_df['Model'].map(compatibility_missing)
    compatibility_df = compatibility_df.sort_values(by=['Missing pieces', 'Compatibility'], ascending=[True, False]).reset_index(drop=True)
    compatibility_df['Total pieces'] = compatibility_df['Model'].apply(lambda x: models_df[(models_df['Model'] == x) & (models_df['Kind'].isin(['regular', 'extra']))]['Qty'].sum())
    compatibility_df['Parts URL'] = compatibility_df['Model'].apply(lambda x: f"[Bricklink {x}](https://www.bricklink.com/CatalogItemInv.asp?S={x}-1)")
    compatibility_df['Instructions URL'] = compatibility_df['Model'].apply(lambda x: f"[Instructions {x}](https://www.lego.com/en-us/service/building-instructions/{x})")
    compatibility_df['Compatibility'] = compatibility_df['Compatibility'].apply(lambda x: f"{x*100:.2f}%")
    return compatibility_df, compatibility_dfs

if not my_models:
    st.info("Please select at least one model to proceed.")
    st.stop()

# Initialize session state
if 'calculated_models' not in st.session_state:
    st.session_state.calculated_models = None
if 'compatibility_df' not in st.session_state:
    st.session_state.compatibility_df = None
if 'compatibility_dfs' not in st.session_state:
    st.session_state.compatibility_dfs = None

# Check if models have changed from the last calculation
models_changed = st.session_state.calculated_models != tuple(my_models)

# Show button only if models changed or no calculation exists yet
if models_changed:
    if st.button("Calculate compatibility"):
        with st.spinner("Calculating compatibility..."):
            compatibility_df, compatibility_dfs = calculate_compatibility(models_df, tuple(my_models))
            compatibility_df = compatibility_df.merge(models_info_df[['Model', 'Name']].drop_duplicates(), on='Model', how='left')
            st.session_state.compatibility_df = compatibility_df
            st.session_state.compatibility_dfs = compatibility_dfs
            st.session_state.calculated_models = tuple(my_models)
            st.rerun()

# Display results if they exist and models haven't changed
if not models_changed and st.session_state.compatibility_df is not None:
    compatibility_df = st.session_state.compatibility_df
    compatibility_dfs = st.session_state.compatibility_dfs

    # Select minimal number of pieces
    min_set_pieces = st.slider("Select minimum number of model pieces:", min_value=0, max_value=1000, value=50, step=10)
    compatibility_df = compatibility_df[compatibility_df['Total pieces'] >= min_set_pieces]

    compatibility_options = compatibility_df.apply(lambda row: f"""[{row['Missing pieces']} | {row['Compatibility']}] {int(row['Model'])} ({available_models[row['Model']]})""", axis=1).tolist()
    compatibility_models = compatibility_df['Model'].tolist()

    selected_model = st.selectbox("Select model by compatibility (**missing pieces | percentage**):", options=compatibility_options[len(my_models):])
    if selected_model:
        selected_model_number = compatibility_models[compatibility_options.index(selected_model)]
        df = compatibility_dfs[selected_model_number]
        st.markdown(f"## Model {selected_model_number} - {available_models[selected_model_number]}")
        st.markdown(f"""- Compatibility: **{compatibility_df[compatibility_df['Model'] == selected_model_number]['Compatibility'].values[0]}**
- Model total pieces: **{compatibility_df[compatibility_df['Model'] == selected_model_number]['Total pieces'].values[0]}**
- Missing pieces: **{compatibility_df[compatibility_df['Model'] == selected_model_number]['Missing pieces'].values[0]}**
- Parts list: [Bricklink ↗](https://www.bricklink.com/CatalogItemInv.asp?S={selected_model_number}-1)
- Building instructions: [LEGO ↗](https://www.lego.com/en-us/service/building-instructions/{selected_model_number})""")
        st.markdown("This is the list of pieces you need to complete the model:")
        df = df.sort_values(by='Missing Qty', ascending=False)
        df['Item No'] = df['Item No'].apply(lambda x: f"[{x}](https://www.bricklink.com/v2/catalog/catalogitem.page?P={x})")
        df['Owned'] = df['Owned'].apply(lambda x: "✅" if x else "❌")
        st.table(df)

    compatibility_df = compatibility_df[['Model', 'Name', 'Total pieces', 'Compatibility', 'Missing pieces', 'Parts URL', 'Instructions URL']]
    st.table(compatibility_df[[c for c in compatibility_df.columns if c != 'text']])