import pandas as pd
import requests
from bs4 import BeautifulSoup

class LegoModelProcessor:
    """Processes LEGO model inventory data from Bricklink."""

    BASE_URL = "https://www.bricklink.com/CatalogItemInv.asp"

    def __init__(self, model_number):
        """Initialize with a model number.

        Args:
            model_number: LEGO model number
        """
        self.model_number = model_number
        self._session = None
    
    def _get_session(self):
        """Get or create requests session."""
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({
                "User-Agent": "Mozilla/5.0",
                "Accept-Language": "en-US,en;q=0.9",
            })
        return self._session
    
    def _fetch_html(self):
        """Fetch inventory HTML from Bricklink."""
        sess = self._get_session()

        def get(set_no):
            r = sess.get(self.BASE_URL, params={"S": set_no, "showOld": "Y"}, timeout=30)
            r.raise_for_status()
            return r.text

        html = get(self.model_number)

        if "No Item(s) were found" in html:
            html = get(f"{self.model_number}-1")

        return html
    
    @staticmethod
    def _to_int(s):
        """Extract integer from string."""
        import re
        _INT = re.compile(r"\d+")
        m = _INT.search(s or "")
        return int(m.group()) if m else 0
    
    def _parse_html(self, html):
        """Parse HTML and create DataFrame."""
        soup = BeautifulSoup(html, "lxml")
        table = soup.select_one("#_idINVContents table.pciinvMainTable")

        if table is None:
            for t in soup.select("table.ta"):
                head = t.get_text(" ", strip=True).lower()
                if "qty" in head and "item" in head and "description" in head:
                    table = t
                    break

        if table is None:
            return pd.DataFrame(columns=["Qty", "Item No", "Description", "Kind"])

        rows = []
        current_type = None

        for tr in table.find_all("tr"):
            cls = tr.get("class", []) or []
            txt = tr.get_text(" ", strip=True).lower()

            # Section headers
            if "regular items" in txt:
                current_type = "regular"
                continue
            if "extra items" in txt:
                current_type = "extra"
                continue
            if "counterparts" in txt:
                current_type = "counterpart"
                continue
            if "alternate" in txt:
                current_type = "alternate"
                continue

            if any(c == "IV_ITEM" for c in cls):
                tds = tr.find_all("td")
                if len(tds) >= 4:
                    rows.append({
                        "Qty": self._to_int(tds[1].get_text(" ", strip=True)),
                        "Item No": (tds[2].find("a").get_text(" ", strip=True)
                                   if tds[2].find("a") else tds[2].get_text(" ", strip=True)),
                        "Description": (tds[3].find("b").get_text(" ", strip=True)
                                       if tds[3].find("b") else tds[3].get_text(" ", strip=True)),
                        "Kind": current_type
                    })

        return pd.DataFrame(rows)

class LegoModelSubsetProcessor:
    """Processes a subset of LEGO model inventory data from Bricklink."""
    
    def __init__(self, models_df):
        """Initialize with a DataFrame of models.

        Args:
            models_df: DataFrame containing LEGO sets data
        """
        self.models_df = models_df
    
    def get_bulk_pieces(self, model_numbers):
        """
        Get pieces for given model numbers from models DataFrame.

        Args:
            model_numbers: List of LEGO model numbers
        Returns:
            DataFrame with pieces for the specified models
        """
        df = self.models_df[self.models_df['Model'].isin(model_numbers)].copy()
        # Filter to regular and extra items only
        df = df[df['Kind'].isin(['regular', 'extra'])]
        # Merge Qty by Item No
        df = df.groupby(['Item No'])['Qty'].sum().reset_index()
        return df

    def compatibility(self, my_df, want_model):
        """How much of my_df (my models) can be found in want_model"""
        want_df = self.get_bulk_pieces([want_model])
        common = want_df.merge(my_df, on='Item No', how='left', suffixes=('_want', '_my'))
        common['Qty_my'] = common['Qty_my'].fillna(0).astype(int)
        common['Qty_diff'] = common['Qty_my'] - common['Qty_want']
        common['Owned'] = common['Qty_diff'] >= 0
        common['Needed Qty'] = common['Qty_want']
        common['Missing Qty'] = common.apply(lambda row: max(0, row['Qty_want'] - row['Qty_my']), axis=1)
        return common[['Item No', 'Owned', 'Needed Qty', 'Missing Qty']]

    def get_compatibility(self, compatibility_df):
        missing = compatibility_df['Missing Qty'].sum()
        percentage = 1 - missing/compatibility_df['Needed Qty'].sum()
        return {'percentage': percentage, 'missing': missing}