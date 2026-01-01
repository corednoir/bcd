import json
import os
import time
from pathlib import Path

# from typing import Union
import ipdb  # 4breakpoint
from playwright.sync_api import Locator, Page, TimeoutError, expect, sync_playwright

import cfg

os.environ["PYTHONBREAKPOINT"] = "ipdb.set_trace"


## ----------------------------------------------
def goto_retry(page, url, max_retries=3, **kwargs):
    for attempt in range(1, max_retries + 1):
        try:
            # print(f"Attempt {attempt} for {url}")
            result = page.goto(url, **kwargs)
            # print(f"Success on attempt {attempt}")
            return result
        except Exception as e:
            print(f"Attempt {attempt} failed: {e}")
            if attempt == max_retries:
                print("Max retries reached. Raising the last exception.")
                return
            print("Retrying...")
    raise Exception("Navigation failed after retries")


def is_owned(thing: Page) -> bool:
    tmp = thing.get_by_text("You own this", exact=True)
    if tmp.count() == 2:  ## one left pane, other below alb pic
        return True
    return False


def assert_count_one(thing: Locator, name="") -> Locator:
    if thing.count() == 1:
        return thing
    else:
        if not name:
            name = thing.text_content()
        print(f"{thing.count()=} {name} found")
        brexit()
        return thing  # rm warn


def extract_number_from_text(text):
    """Extracts the first number found in the text (including decimal point)."""
    number_str = ""
    found_decimal = False
    for char in text:
        if char.isdigit():
            number_str += char
        elif char == "." and not found_decimal:  # only first
            number_str += char
            found_decimal = True
        elif number_str and not char.isdigit() and char != ".":
            break
    if number_str:
        print(f"\t{text}\n\t  -->{number_str}")
        return number_str
    return None


def brexit():
    breakpoint()
    exit()


def get_basket_fn():
    basket_fn = getattr(cfg, "BASKET_FILE", None)
    if basket_fn is None:
        assert getattr(cfg, "BC_URL", None) is not None
        basket_fn = cfg.BC_URL.split(".bandcamp.com")[0].replace("https://", "")
        basket_fn = f"data/{basket_fn}.json"
    # assert os.path.exists(basket_fn)
    return basket_fn


def get_authenticated_context(browser):
    if os.path.exists(cfg.AUTH_FILE):
        print("Found existing auth — restoring session...")
        context = browser.new_context(
            storage_state=cfg.AUTH_FILE, viewport=cfg.VIEWPORT
        )
    else:
        print("No auth found — please log in.")
        context = browser.new_context()
        page = context.new_page()
        goto_retry(page, "https://bandcamp.com/login")
        input("Press Enter after logging in...")
        context.storage_state(path=cfg.AUTH_FILE)
        print(f"Auth saved to {cfg.AUTH_FILE}")
        # Re-create context after saving state
        context = browser.new_context(
            storage_state=cfg.AUTH_FILE, viewport=cfg.VIEWPORT
        )

    return context


## ----------------------------------------------
# JSON
def load_basket():
    """
    Loads the existing todbasket.json file.
    Expects the file to contain an object like:
    {
      "albums": [...],
      "skipped": [...]
    }
    Where 'albums' is the list of albums to process, and 'skipped' is a list of URLs to skip.
    If the file doesn't exist, it initializes an empty structure.
    Returns (albums_list, skipped_urls_set).
    """
    basket_fn = get_basket_fn()
    path = Path(basket_fn)
    if path.is_file():
        print(f"Loading existing basket from {basket_fn}...")
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)

            # Check if the loaded data has the expected structure
            if isinstance(data, dict) and "albums" in data and "skipped" in data:
                basket_albums = data.get("albums", [])
                skipped_urls = set(data.get("skipped", []))
                print(
                    f"Loaded {len(basket_albums)} albums to process and {len(skipped_urls)} skipped URLs."
                )
                return basket_albums, skipped_urls
            else:
                print(f"Warning: {basket_fn} has an unexpected format. Starting fresh.")
                return [], set()

        except json.JSONDecodeError:
            print(f"Error: {basket_fn} is not valid JSON. Starting fresh.")
            return [], set()
    else:
        print(f"No existing basket file ({basket_fn}) found. Starting fresh.")
        return [], set()


def save_basket(basket_albums, skipped_urls):
    """
    Saves the current basket albums and skipped URLs to todbasket.json.
    Converts the skipped_urls set back to a sorted list for JSON serialization.
    """
    basket_fn = get_basket_fn()
    path = Path(basket_fn)
    if path.is_file():
        a = input(f"overwrite {basket_fn}")
        if a not in ["y", "yes"]:
            return
    data_to_save = {
        "albums": basket_albums,
        # conv set back to a sorted list
        "skipped": sorted(list(skipped_urls)),
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(data_to_save, f, ensure_ascii=False, indent=2)
    print(f"Basket saved to {basket_fn}.")


## ----------------------------------------------
def add_to_basket_interactive():
    """Interactively adds albums to the basket or marks them as skipped."""
    basket_albums, skipped_urls = load_basket()
    existing_urls = {album["url"] for album in basket_albums}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=150)

        context = get_authenticated_context(browser)

        page = context.new_page()

        # --- Navigate and Extract Albums ---
        goto_retry(page, cfg.BC_URL)

        print("Waiting for music section...")
        try:
            music_grid_item_locator = page.locator("li.music-grid-item")
            music_grid_item_locator.first.wait_for(state="attached", timeout=10000)
            count = music_grid_item_locator.count()
            print(f"Found {count} music grid items.")
        except TimeoutError:
            print("Timeout: Could not find 'li.music-grid-item' after waiting.")
            page.screenshot(path="debug_screenshot_add.png", full_page=True)
            browser.close()
            return

        breakpoint()

        albums = page.eval_on_selector_all(
            "li.music-grid-item",
            """els => els.map(el => {
                const a = el.querySelector('a[href]');
                const titleEl = el.querySelector('.title');
                if (!a || !titleEl) return null;

                let title = titleEl.textContent.trim();
                let artist = '';
                const br = titleEl.querySelector('br');
                if (br && br.nextSibling) {
                    artist = br.nextSibling.textContent.trim();
                }

                // Clean up URL and text
                const url = a.href ? a.href.trim() : null;
                title = title ? title.split('\\n')[0].trim() : '';
                return {
                    url: url,
                    title: title,
                    artist: artist || 'Various Artists'
                };
            }).filter(Boolean)""",
        )

        print(f"--- Starting Interactive Addition ({len(albums)} albums found) ---")
        print(
            "'y' to add album, 'n' to skip, 's' to save and stop adding, 'c' to cancel w/o saving."
        )

        for i, album in enumerate(albums):
            album_url = album["url"].strip()

            if album_url in cfg.album_urls_to_skip:
                continue

            if album_url in skipped_urls:
                print(
                    f"  Album {album['title']} by {album['artist']} (URL: {album_url}) marked as skipped. Skipping."
                )
                continue

            if album_url in existing_urls:
                print(
                    f"  Album {album['title']} by {album['artist']} (URL: {album_url}) is already in the basket. Skipping."
                )
                continue

            print(
                f"  [{i + 1}/{len(albums)}] Checking: {album['title']} — {album['artist']}"
            )
            print(f"                URL: {album_url}")

            res = goto_retry(page, album_url)
            if not res:
                user_input = input("  save prior to exit? (y/n): ").strip().lower()
                if user_input in ["y", "yes"]:
                    save_basket(basket_albums, skipped_urls)
                    print("  Basket saved. Stopping interactive addition.")
                context.close()
                browser.close()

            if is_owned(page):
                print("  already owned")
                continue

            while True:
                user_input = input("  Add to basket? (y/n/s/c): ").strip().lower()
                if user_input in ["y", "yes"]:
                    basket_albums.append(album)
                    existing_urls.add(
                        album_url
                    )  # Update the set for subsequent checks in this run
                    print(f"    Added '{album['title']}' to basket.")
                    break  # Move to next album
                elif user_input in ["n", "no"]:  # Add to skipped set
                    skipped_urls.add(album_url)
                    print(f"    Marked '{album['title']}' as skipped.")
                    break  # Move to next album
                elif user_input in ["s", "save"]:
                    save_basket(basket_albums, skipped_urls)
                    print("  Basket saved. Stopping interactive addition.")
                    context.close()
                    browser.close()
                    return  # Exit the function after saving
                elif user_input in ["c", "cancel"]:
                    print("  Cancelled. No changes saved.")
                    context.close()
                    browser.close()
                    return  # Exit the function without saving
                else:
                    print("  Invalid input. Please enter 'y', 'n', 's', or 'c'.")

        print("\n--- Finished scanning albums. ---")
        save_basket(basket_albums, skipped_urls)
        print(
            f"Final basket contains {len(basket_albums)} albums to process and {len(skipped_urls)} skipped."
        )
        context.close()
        browser.close()


## ----------------------------------------------
def download_basket():
    """Loads the basket and performs download actions (placeholder)."""
    basket_albums, skipped_urls = load_basket()  # Load both lists
    if not basket_albums:
        print("The download basket is empty. Nothing to process.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=150)

        context = get_authenticated_context(browser)

        page = context.new_page()

        print(f"Starting download process for {len(basket_albums)} albums...")
        for i, album in enumerate(basket_albums):
            print(
                f"  [{i + 1}/{len(basket_albums)}] Processing: {album['title']} by {album['artist']}"
            )
            print(f"                URL: {album['url']}")

            goto_retry(page, album["url"])

            if is_owned(page):
                print("  already owned")
                continue

            ## ----------------------
            ## click buy digital algum button with
            # <h4 class="ft compound-button main-button">
            #     <button class="download-link buy-link" type="button">
            #         Buy Digital Album
            #     </button>&nbsp;
            #     <span class="buyItemExtra buyItemNyp secondaryText">name your price</span>
            #   OR
            #    <span class="nobreak">
            #        <span class="base-text-color">£7</span>
            #        <span class="buyItemExtra secondaryText">GBP</span>
            #    <span class="buyItemExtra buyItemNyp secondaryText">&nbsp;or more</span>
            #    </span>
            # </h4>
            buy_div = page.locator("h4.ft.compound-button.main-button")
            buy_div_text = buy_div.all_inner_texts()[0]
            if "name your price" in buy_div_text:
                amount = "0"
                print("nyp")
            else:
                amount = extract_number_from_text(buy_div_text)
                assert amount is not None
                print(amount)

            ## ----------------------
            buy_but = page.locator(
                "button.download-link.buy-link", has_text="Buy Digital"
            )
            buy_but = assert_count_one(buy_but)
            buy_but.click()  # click triggers a widget

            ## ----------------------
            ## fill amount
            amn_inp = page.get_by_label("Enter amount:")
            amn_inp = assert_count_one(amn_inp)
            amn_inp.fill(amount)  # :(

            ## check if min amount is need to add to bc collection
            # Pay £0.50 GBP or more to add this release to your Bandcamp collection, get
            # unlimited mobile streaming, and directly support ___.
            # Alternatively, continue with zero and download to your computer.
            min_amn_to_collect_div = page.locator(
                "div.section.payment-nag-section", has_text="download to your computer"
            )
            expect(min_amn_to_collect_div).to_be_visible(timeout=5000)
            if min_amn_to_collect_div.is_visible():
                print("min_amount visible")
                tmp = min_amn_to_collect_div.all_inner_texts()[0]
                amount = extract_number_from_text(tmp)
                if amount is not None:
                    amn_inp.fill(amount)
                else:
                    brexit()

            ## ----------------------
            ## thn add to basket button
            bsk_but = page.get_by_text("Add to cart")
            bsk_but = assert_count_one(bsk_but)
            bsk_but.click()
            # <div class="cart-button-wrapper">
            #     <button type="button" data-bind="click: addToCart">Add to cart</button>
            # </div>

        # -----------------------
        ckc_but = page.get_by_text("Check out")
        ckc_but = assert_count_one(ckc_but)
        ckc_but.click()

        # -----------------------
        tmp = page.get_by_text("x-3350")
        page.evaluate(
            "element => element.innerHTML = '(1 303 303$)'",
            tmp.element_handle(),
        )

        # -----------------------
        end_but = page.get_by_text("Complete purchase")
        end_but = assert_count_one(end_but)

        user_input = input("  sure? (y/n): ").strip().lower()
        if user_input in ["y", "yes"]:
            end_but.scroll_into_view_if_needed()
            user_input = input("  4real? (y/n): ").strip().lower()
            if user_input in ["y", "yes"]:
                end_but.click()

        context.close()
        browser.close()


def main():
    print("\n--- Bandcamp Album Basket Manager ---")
    print("1. Add albums to basket interactively")
    print("2. Download albums from basket")
    print("3. View current basket")
    choice = input("Choose an option (1/2/3): ").strip()

    if choice == "1":
        add_to_basket_interactive()
    elif choice == "2":
        download_basket()
    elif choice == "3":
        basket_albums, skipped_urls = load_basket()
        print(
            f"\n--- Current Basket ({len(basket_albums)} items to process, {len(skipped_urls)} skipped) ---"
        )
        if basket_albums:
            print("\nAlbums to Process:")
            for i, album in enumerate(basket_albums, 1):
                print(f"  {i:2}. {album['title']} — {album['artist']}")
                print(f"     → {album['url']}")
        else:
            print("\nNo albums to process.")

        if skipped_urls:
            print(f"\nSkipped URLs ({len(skipped_urls)}):")
            for url in sorted(skipped_urls):  # Sort for consistent display
                print(f"  - {url}")
        else:
            print("\nNo URLs marked as skipped.")

    else:
        print("Invalid choice. Exiting.")


if __name__ == "__main__":
    main()
