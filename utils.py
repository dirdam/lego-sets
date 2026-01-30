import pandas as pd
import requests
from bs4 import BeautifulSoup
import streamlit as st
from io import BytesIO
try:
    from pypdf import PdfReader
except ImportError:
    from PyPDF2 import PdfReader
from pdf2image import convert_from_bytes
import pytesseract
from PIL import Image
import numpy as np

class LegoModelProcessor:
    """Processes LEGO model inventory data from Bricklink."""
    
    BASE_URL = "https://www.bricklink.com/CatalogItemInv.asp"
    
    GENERAL_WORDS = ['axle', 'gear', 'connector', 'pin', 'liftarm', 'bush']
    SPECIFIC_WORDS = ['modified']
    
    MECHANICS_WORDS = [
        # Gearing / transmission
        'gear', 'differential', 'clutch', 'ratchet', 'planetary', 'gearbox',
        # Motion conversion / kinematics
        'crank', 'cam', 'rack', 'actuator', 'screw',
        # Rotary systems
        'turntable', 'pulley', 'winch', 'chain', 'belt',
        # Wheels / driven motion
        'wheel', 'track',
        # Suspension / elastic motion
        'shock', 'spring',
        # Pneumatics
        'pneumatic', 'pump', 'valve', 'cylinder', 'hose',
        # Powered / electronic
        'motor', 'servo', 'hub', 'battery', 'sensor', 'remote'
    ]
    
    def __init__(self, model_number, enable_ocr=False, verbose=False):
        """Initialize with a model number.

        Args:
            model_number: LEGO model number
            enable_ocr: If True, perform OCR to count steps (slow). Default False.
            verbose: If True, print debug messages. Default False.
        """
        self.model_number = model_number
        self.df = None
        self._session = None
        self.enable_ocr = enable_ocr
        self.verbose = verbose
    
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
        if self.verbose:
            print(f"DEBUG: _fetch_html() starting for model {self.model_number}")
        sess = self._get_session()
        if self.verbose:
            print(f"DEBUG: Session created")

        def get(set_no):
            if self.verbose:
                print(f"DEBUG: Fetching HTML for set number: {set_no}")
            r = sess.get(self.BASE_URL, params={"S": set_no, "showOld": "Y"}, timeout=30)
            r.raise_for_status()
            if self.verbose:
                print(f"DEBUG: HTML fetched successfully, length: {len(r.text)}")
            return r.text

        html = get(self.model_number)

        if "No Item(s) were found" in html:
            if self.verbose:
                print(f"DEBUG: No items found, retrying with {self.model_number}-1")
            html = get(f"{self.model_number}-1")

        if self.verbose:
            print(f"DEBUG: _fetch_html() completed")
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
        if self.verbose:
            print(f"DEBUG: _parse_html() starting, HTML length: {len(html)}")
        soup = BeautifulSoup(html, "lxml")
        if self.verbose:
            print(f"DEBUG: BeautifulSoup parsing complete")
        name_el = soup.select_one('center font > b')
        name = name_el.get_text(strip=True) if name_el else '?'
        self.model_name = name
        if self.verbose:
            print(f"DEBUG: Model name extracted: {name}")
        table = soup.select_one("#_idINVContents table.pciinvMainTable")
        
        if table is None:
            for t in soup.select("table.ta"):
                head = t.get_text(" ", strip=True).lower()
                if "qty" in head and "item" in head and "description" in head:
                    table = t
                    break
        
        if table is None:
            if self.verbose:
                print(f"DEBUG: No table found, returning empty DataFrame")
            return pd.DataFrame(columns=["Qty", "Item No", "Description", "Kind"])

        if self.verbose:
            print(f"DEBUG: Table found, starting to parse rows")
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

        if self.verbose:
            print(f"DEBUG: Parsed {len(rows)} rows from table")
        return pd.DataFrame(rows)
    
    def _classify_generality(self, text):
        """Classify part as general or specific."""
        text = text.lower()
        for word in self.SPECIFIC_WORDS:
            if word in text.split(' '):
                return 'specific'
        for word in self.GENERAL_WORDS:
            if word in text.split(' '):
                return 'general'
        return 'specific'
    
    def _classify_mechanics(self, text):
        """Classify part as mechanics or normal."""
        text = text.lower()
        for word in self.MECHANICS_WORDS:
            if word in text.split(' '):
                return 'mechanics'
        return 'normal'
    
    def process(self, show_stats=True):
        """
        Process the model and return enriched DataFrame.

        Args:
            show_stats: If True, print statistics

        Returns:
            DataFrame with inventory data and classifications
        """
        if self.verbose:
            print(f"DEBUG: process() starting for model {self.model_number}")
        # Fetch and parse data
        html = self._fetch_html()
        if self.verbose:
            print(f"DEBUG: HTML fetched, parsing now")
        self.df = self._parse_html(html)
        if self.verbose:
            print(f"DEBUG: DataFrame created with {len(self.df)} rows")

        # Filter out counterparts
        self.df = self.df[self.df['Kind'] != 'counterpart']
        if self.verbose:
            print(f"DEBUG: After filtering counterparts: {len(self.df)} rows")

        # Add classifications
        if self.verbose:
            print(f"DEBUG: Adding Specificity classifications")
        self.df['Specificity'] = self.df['Description'].apply(self._classify_generality)
        if self.verbose:
            print(f"DEBUG: Adding Mechanics classifications")
        self.df['Mechanics'] = self.df['Description'].apply(self._classify_mechanics)

        # Print statistics if show_stats
        if show_stats:
            if self.verbose:
                print(f"DEBUG: Printing statistics (show_stats=True)")
            self.print_stats()

        if self.verbose:
            print(f"DEBUG: process() completed")
        return self.df
    
    def get_count(self, category='total', unique=False):
        """
        Get count of parts by category.
        
        Args:
            category: 'total', 'general', or 'mechanics'
            unique: If True, count unique parts; if False, count total quantity
            
        Returns:
            Integer count
        """
        if self.df is None:
            raise ValueError("Call process() first")
        
        temp = self.df[self.df['Kind'] != 'counterpart']
        
        if category == 'general':
            filtered = temp[temp['Specificity'] == 'general']
        elif category == 'mechanics':
            filtered = temp[temp['Mechanics'] == 'mechanics']
        else:
            filtered = temp
        
        if unique:
            return filtered['Item No'].nunique()
        return filtered['Qty'].sum()
    
    def get_generality_ratio(self):
        """Calculate generality ratio (general parts / total parts)."""
        if self.df is None:
            raise ValueError("Call process() first")
        
        total = self.get_count('total')
        general = self.get_count('general')
        return general / total if total > 0 else 0
    
    def get_instructions(self):
        """
        Get building instructions with metadata.

        Returns:
            List of dictionaries with 'url', 'pages', and optionally 'steps' keys
        """
        if self.verbose:
            print(f"DEBUG: get_instructions() starting - fetching instruction links")
        instructions = self.fetch_building_instructions()
        if self.verbose:
            print(f"DEBUG: Found {len(instructions)} instruction PDFs")
        result = []
        for i, link in enumerate(instructions):
            if self.verbose:
                print(f"DEBUG: Processing instruction {i+1}/{len(instructions)}: {link}")
                print(f"DEBUG: Counting pages for instruction {i+1}")
            pages = self.count_pdf_pages(link)

            instruction_data = {
                'url': link,
                'pages': pages,
            }

            if self.enable_ocr:
                if self.verbose:
                    print(f"DEBUG: Found {pages} pages, now counting steps (OCR enabled)")
                steps = self.count_steps(link)
                if self.verbose:
                    print(f"DEBUG: Found {steps} steps")
                instruction_data['steps'] = steps
            else:
                if self.verbose:
                    print(f"DEBUG: Found {pages} pages, skipping step counting (OCR disabled)")
                instruction_data['steps'] = None

            result.append(instruction_data)
        if self.verbose:
            print(f"DEBUG: get_instructions() completed")
        return result

    def print_stats(self):
        """Print summary statistics."""
        if self.verbose:
            print(f"DEBUG: print_stats() starting")
        if self.df is None:
            raise ValueError("Call process() first")

        if self.verbose:
            print(f"DEBUG: Calculating counts")
        total = self.get_count('total')
        general = self.get_count('general')
        ratio = self.get_generality_ratio()
        total_unique = self.get_count('total', unique=True)
        mechanics_unique = self.get_count('mechanics', unique=True)
        if self.verbose:
            print(f"DEBUG: Getting instructions (this may take a while)")
        instructions = self.get_instructions()
        if self.verbose:
            print(f"DEBUG: Got {len(instructions)} instructions")

        with st.expander(f"Statistics for model **{self.model_number}**", expanded=True):
            stats = f"""
| | **Value** |
|-|-|
| **Model name** | {self.model_name} |
| **General parts** | {general} |
| **Total parts** | {total} |
| **Generality ratio** | {ratio:.2%} |
| **Unique pieces** | {total_unique} |
| **Unique mechanical pieces** | {mechanics_unique} |
"""
            st.markdown(stats)
            # Build dynamic table header
            header = "| |"
            separator = "|-|"
            link_row = "| **Instruction PDFs** |"
            pages_row = "| **Pages** |"

            # Only show steps row if OCR is enabled
            if self.enable_ocr:
                steps_row = "| **Steps** |"

            for i, instruction in enumerate(instructions):
                header += f" PDF {i+1} |"
                separator += "-|"
                link_row += f" [{instruction['url'].replace(' ', '^').split('/')[-1][:-4]}]({instruction['url'].replace(' ', '-')}) |"
                pages_row += f" {instruction['pages']} |"
                if self.enable_ocr:
                    steps_row += f" {instruction['steps']} |"

            # Build table with or without steps row
            if self.enable_ocr:
                instructions_table = f"""
{header}
{separator}
{link_row}
{pages_row}
{steps_row}
"""
            else:
                instructions_table = f"""
{header}
{separator}
{link_row}
{pages_row}
"""
            st.markdown(instructions_table)

    def fetch_building_instructions(self):
        """
        Fetch all PDF building instruction links from LEGO website.

        Returns:
            List of PDF download URLs
        """
        url = f"https://www.lego.com/en-us/service/building-instructions/{self.model_number}"
        if self.verbose:
            print(f"DEBUG: fetch_building_instructions() fetching from {url}")
        sess = self._get_session()

        try:
            r = sess.get(url, timeout=30)
            r.raise_for_status()
            if self.verbose:
                print(f"DEBUG: Successfully fetched instructions page")
        except requests.RequestException as e:
            raise RuntimeError(f"Failed to fetch building instructions: {e}")

        if self.verbose:
            print(f"DEBUG: Parsing instructions page HTML")
        soup = BeautifulSoup(r.text, "lxml")

        # Find all PDF download links
        pdf_links = []

        # Look for download links in the main content area
        main_content = soup.select_one("#main-content")
        if main_content:
            # Find all <a> tags that might contain PDF links
            for link in main_content.find_all("a", href=True):
                href = link.get("href", "")
                # Check if the link points to a PDF
                if href.endswith(".pdf"):
                    # Convert relative URLs to absolute
                    if href.startswith("http"):
                        pdf_links.append(href)
                    elif href.startswith("//"):
                        pdf_links.append(f"https:{href}")
                    elif href.startswith("/"):
                        pdf_links.append(f"https://www.lego.com{href}")

        if self.verbose:
            print(f"DEBUG: Found {len(pdf_links)} PDF links")
        return pdf_links

    def count_pdf_pages(self, pdf_url):
        """
        Download a PDF from the given URL and count its pages.

        Args:
            pdf_url: URL of the PDF to download and analyze

        Returns:
            Integer number of pages in the PDF
        """
        if self.verbose:
            print(f"DEBUG: count_pdf_pages() downloading PDF from {pdf_url}")
        sess = self._get_session()

        try:
            r = sess.get(pdf_url, timeout=60)
            r.raise_for_status()
            if self.verbose:
                print(f"DEBUG: PDF downloaded, size: {len(r.content)} bytes")
        except requests.RequestException as e:
            raise RuntimeError(f"Failed to download PDF from {pdf_url}: {e}")

        # Read PDF from bytes
        pdf_file = BytesIO(r.content)

        try:
            reader = PdfReader(pdf_file)
            page_count = len(reader.pages)
            if self.verbose:
                print(f"DEBUG: PDF has {page_count} pages")
            return page_count
        except Exception as e:
            raise RuntimeError(f"Failed to read PDF: {e}")

    def count_steps(self, pdf_url):
        """
        Extract step numbers from the upper left quadrant of each page using OCR.

        Args:
            pdf_url: URL of the PDF to download and analyze

        Returns:
            List of extracted step numbers (as strings) for each page
        """
        if self.verbose:
            print(f"DEBUG: count_steps() downloading PDF from {pdf_url}")
        sess = self._get_session()

        try:
            r = sess.get(pdf_url, timeout=60)
            r.raise_for_status()
            if self.verbose:
                print(f"DEBUG: PDF downloaded for OCR, size: {len(r.content)} bytes")
        except requests.RequestException as e:
            raise RuntimeError(f"Failed to download PDF from {pdf_url}: {e}")

        # Progress: PDF to Images conversion
        conversion_progress = st.progress(0, text="Converting PDF to images...")
        try:
            # Convert PDF pages to images
            if self.verbose:
                print(f"DEBUG: Converting PDF to images (this may take a while)")
            images = convert_from_bytes(r.content)
            conversion_progress.progress(100, text=f"✓ Converted to {len(images)} images")
            if self.verbose:
                print(f"DEBUG: Converted to {len(images)} images")
        except Exception as e:
            conversion_progress.empty()
            raise RuntimeError(f"Failed to convert PDF to images: {e}")

        # Progress: OCR processing
        ocr_progress = st.progress(0, text="Processing OCR on pages...")
        step_numbers = []

        for page_num, image in enumerate(images, 1):
            # Update progress bar
            progress_percent = int((page_num / len(images)) * 100)
            ocr_progress.progress(progress_percent, text=f"Processing OCR: page {page_num}/{len(images)}")
            if self.verbose:
                print(f"DEBUG: Processing OCR for page {page_num}/{len(images)}")

            try:
                # Get dimensions
                width, height = image.size

                # Define upper left quadrant (top 50% height, left 25% width)
                quadrant_width = width // 4
                quadrant_height = height // 2

                # Crop to upper left quadrant
                upper_left = image.crop((0, 0, quadrant_width, quadrant_height))

                # Perform OCR with configuration optimized for numbers
                # --psm 6: Assume a single uniform block of text
                # --oem 3: Default OCR Engine Mode
                # -c tessedit_char_whitelist=0123456789: Only recognize digits
                custom_config = r'--psm 6 --oem 3 -c tessedit_char_whitelist=0123456789'
                text = pytesseract.image_to_string(upper_left, config=custom_config)

                # Extract numbers from the OCR result
                extracted = text.strip()
                step_numbers.append(extracted if extracted else None)

            except Exception as e:
                # If OCR fails for a page, append None
                if self.verbose:
                    print(f"DEBUG: OCR failed for page {page_num}: {e}")
                step_numbers.append(None)

        # Mark OCR as complete
        ocr_progress.progress(100, text=f"✓ OCR complete ({len(images)} pages processed)")

        if self.verbose:
            print(f"DEBUG: OCR complete, processing step numbers")
        step_numbers = [s for s in step_numbers if s is not None]
        if self.verbose:
            print(f"DEBUG: Filtered to {len(step_numbers)} non-None results")
        step_numbers = sorted([int(s) for s in step_numbers if s.isdigit() and int(s) < 1000])  # Filter out non-numeric and pieces numbers
        if self.verbose:
            print(f"DEBUG: Sorted and filtered to {len(step_numbers)} valid numbers")
        diffs = [b - a for a, b in zip(step_numbers[:-1], step_numbers[1:])]
        max_gap_index = diffs.index(max(diffs))
        if self.verbose:
            print(f"DEBUG: Step numbers before gap: {step_numbers[:max_gap_index + 1]}")
            print(f"DEBUG: Step numbers after gap: {step_numbers[max_gap_index + 1:]}")
        result = max(step_numbers[:max_gap_index + 1])
        if self.verbose:
            print(f"DEBUG: count_steps() returning {result}")
        return result
    
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
        common['Compatible'] = common['Qty_diff'] >= 0
        return common[['Item No', 'Compatible']]

    def get_compatibility(self, compatibility_df):
        return compatibility_df['Compatible'].sum()/len(compatibility_df)
