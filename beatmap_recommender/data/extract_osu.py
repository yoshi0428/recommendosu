import os
import zipfile

from tqdm import tqdm


ROOT_DIR = "./2024 (osu!)"
OUTPUT_DIR = "2024_osu"


def extract_osu_files(root_dir, output_dir):
    """
    Recursively find .osz archives and extract only .osu files.
    All .osu files are placed directly into output_dir.
    """
    os.makedirs(output_dir, exist_ok=True)

    osz_files = []
    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename.lower().endswith(".osz"):
                osz_files.append(
                    os.path.join(dirpath, filename)
                )

    print(f"Found {len(osz_files)} .osz archives.")

    extracted_count = 0

    for osz_path in tqdm(osz_files, desc="Extracting .osu files"):

        try:
            with zipfile.ZipFile(osz_path, "r") as archive:
                for member in archive.infolist():

                    if not member.filename.lower().endswith(".osu"):
                        continue

                    filename = os.path.basename(member.filename)

                    if not filename:
                        continue

                    output_path = os.path.join(output_dir, filename)

                    if os.path.exists(output_path):

                        base, extension = os.path.splitext(filename)

                        counter = 1
                        while True:
                            new_filename = (f"{base}_{counter}{extension}")
                            output_path = os.path.join(output_dir, new_filename)

                            if not os.path.exists(output_path):
                                break

                            counter += 1

                    with archive.open(member) as source, open(output_path, "wb") as target:
                        target.write(source.read())

                    extracted_count += 1

        except zipfile.BadZipFile:
            print(f"\nInvalid .osz archive: {osz_path}")
        except Exception as e:
            print(f"\nFailed to extract {osz_path}: {e}")

    print(f"\nExtracted {extracted_count} .osu files.")

if __name__ == "__main__":
    extract_osu_files(
        ROOT_DIR,
        OUTPUT_DIR
    )