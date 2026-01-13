

\# Duplicate \& Similar Media Finder



A local Python application to detect and clean duplicate and visually similar

images and videos from a folder.



\## Features



\- Exact duplicate detection (any file type) using SHA-256 hashing

\- Similar image detection using perceptual hash (pHash)

\- Similar video detection using keyframe pHash

\- Interactive UI built with Streamlit

\- Select duplicates directly from thumbnails

\- Safe cleanup: files are moved to a timestamped `\_duplicates\_` folder

\- Caching for faster re-scans



\## Tech Stack



\- Python

\- Streamlit

\- Pillow

\- ImageHash

\- OpenCV

\- NumPy, SciPy



\## How to Run



1\. Clone the repository:



git clone https://github.com/hemugithub6329/duplicate-media-finder.git

cd duplicate-media-finder



2\. Create and activate virtual environment:



python -m venv venv

venv\\Scripts\\activate



3\. Install dependencies:



pip install -r requirements.txt



4\. Run the app:



streamlit run app.py



\## Notes



\* The application works on local folders

\* Files are never deleted permanently

\* Duplicate files are moved to a separate folder for safety





