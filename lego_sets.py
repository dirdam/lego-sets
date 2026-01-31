import streamlit as st
import pandas as pd
import utils

st.markdown("# LEGO Sets")

# ========== Process all Technic models ==========
# (Run update only once in a while, when new sets are released)

models_df = pd.read_csv("lego_sets.csv")
if st.button("Update LEGO dataset"):
    sets_to_explore = range(42000, 43000)
    technic_models = [i for i in sets_to_explore]

    progress_bar = st.progress(0)
    spinner_placeholder = st.empty()
    for idx, model in enumerate(technic_models):
        progress_bar.progress((idx + 1) / len(technic_models))
        if model in models_df['Model'].values:
            spinner_placeholder.text(f"Model {model} already in dataset")
        else:
            spinner_placeholder.text(f"Processing model: {model}")
            processor = utils.LegoModelProcessor(model)
            html = processor._fetch_html()
            df = processor._parse_html(html)
            if len(df) == 0:
                spinner_placeholder.text(f"> Model {model} not found, skipping")
                continue
            df['Model'] = model
            models_df = pd.concat([models_df, df], ignore_index=True)
            models_df = models_df.sort_values(by=['Model', 'Item No', 'Description'])
            models_df.to_csv("lego_sets.csv", index=False)
    spinner_placeholder.empty()
    progress_bar.empty()

# ========== Fetch my models ==========

col1, col2, col3 = st.columns(3)
with col1:
    my_model1 = st.checkbox("Include 42218 (John Deere)", value=True)
with col2:
    my_model2 = st.checkbox("Include 42108 (Crane)", value=True)
with col3:
    my_model3 = st.checkbox("Include 42175 (Truck & Excavator)", value=True)
my_models = []
if my_model1:
    my_models.append(42218)
if my_model2:
    my_models.append(42108)
if my_model3:
    my_models.append(42175)

@st.cache_data
def calculate_compatibility(models_df, my_models):
    finder = utils.LegoModelSubsetProcessor(models_df)
    my_df = finder.get_bulk_pieces(my_models[:])
    compatibility_values = {}
    compatibility_dfs = {}
    for model in models_df['Model'].unique():
        compatibility_df = finder.compatibility(my_df, model)
        compatibility_value = finder.get_compatibility(compatibility_df)
        compatibility_values[model] = compatibility_value
        compatibility_dfs[model] = compatibility_df
    # Convert dict to DataFrame for display
    compatibility_df = pd.DataFrame(list(compatibility_values.items()), columns=['Model', 'Compatibility'])
    compatibility_df = compatibility_df.sort_values(by='Compatibility', ascending=False).reset_index(drop=True)
    compatibility_df['text'] = compatibility_df.apply(lambda row: f"{int(row['Model'])} ({row['Compatibility']*100:.2f}%)", axis=1)
    compatibility_df['Parts URL'] = compatibility_df['Model'].apply(lambda x: f"[Bricklink {x}](https://www.bricklink.com/CatalogItemInv.asp?S={x}-1)")
    compatibility_df['Instructions URL'] = compatibility_df['Model'].apply(lambda x: f"[Instructions {x}](https://www.lego.com/en-us/service/building-instructions/{x})")
    return compatibility_df, compatibility_dfs

compatibility_df, compatibility_dfs = calculate_compatibility(models_df, tuple(my_models))
selected_model = st.selectbox("Select model", options=compatibility_df['text'].tolist()[len(my_models):])
if selected_model:
    selected_model_number = int(selected_model.split(' ')[0])
    df = compatibility_dfs[selected_model_number]
    with st.expander(f"Missing pieces", expanded=False):
        st.dataframe(df[df['Compatible'] == False])

st.table(compatibility_df[[c for c in compatibility_df.columns if c != 'text']])