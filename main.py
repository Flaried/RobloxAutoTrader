import time
import traceback
from rolimons_api import RolimonAPI
from roblox_api import RobloxAPI
from trade_algorithm import TradeMaker
from handler import *
import threading
from datetime import datetime, timedelta
from handler.handle_json import JsonHandler
from account_manager import AccountManager
import config_manager
from handler.account_settings import HandleConfigs
import os
import sys
from whitelist_manager import WhitelistManager
from handler.handle_whitelist import Whitelist

"""
    have total value gain (total value of items traded)

    if account has no value items, maybe swatch to rap_config.cfg?
    have value_config.cfg

    fix outbound checking cancel outbounds thats above the max
    Fix bad imports and messy imports..


    1. multithread appending owners (bake in get inventory so multiple threads work on inventories)
    maybe have projected scanning in another thread somehow? dont let the whole program wait on 1 thread for projected scanning

    Rolimon ads and discord ads for more counters!

    Trade send thread should be seprate from scanning inventories threads bc ratelimit on resale-data

    dont keep countering trades from same person
    also switch users if coulndt find trade in like 30 minutes
"""

class Doggo:
    def __init__(self):
        """
            Store all the variables that will be used across doggo class
        """
        self.user_queue = {}
        self.cli = Terminal()
        self.json = JsonHandler(filename="cookies.json")
        self.rolimons = RolimonAPI()

        # NOTE: use roblo accounts trademaker
        #self.trader = TradeMaker()
        self.account_configs = HandleConfigs()
        self.discord_webhook = DiscordHandler()
        self.whitelist = Whitelist()
        self.whitelist_manager = WhitelistManager()

        # Define a stop event that will be shared between threads
        self.stop_event = threading.Event()


        # Time Stamps for Routines
        self.whitelist_checked = time.time()
        self.last_updated_rolimons = time.time()
        self.last_checked_trades = time.time()

    def validate_whitelist(self):
        """
            Returns True or False weither the server could validate the credentials in .whitelist file
            Will Return None if something went wrong
        """
        while True:
            try:
                if not os.path.isfile(".whitelist"):
                    print("sending to whitelist menu")
                    self.whitelist_manager.main()
                data = self.whitelist_manager.json.read_data()
                if data and data.get('username') and data.get('password') and data.get('orderid'):
                    if self.whitelist.is_valid(data['username'], data['password'], data['orderid']):
                        return True
                    else:
                        return False
                else:
                    print("Please enter some login details.")
                    time.sleep(1)
                    self.whitelist_manager.main()
            except Exception as e:
                print("Couldn't validate whitelist", e)
                raise ValueError("Couldn't validate Whitelist")

    def main(self):
        """
        A loop that runs the Menu and clears the console
        """
        while True:
            self.cli.clear_console()
            self.display_main_menu()
    
    def display_main_menu(self):
        """
        CLI Menu that has a bunch of options and handles the selected answer
        """
        options = (
            (1, "Account Manager"),
            (2, "Config Manager"),
            (3, "Whitelist Manager"),
            (4, "Execute Trader"),
        )
        print("Version: 0.5 (BETA)")
        self.cli.print_menu("Main Menu", options)
        try:
            answer = int(self.cli.input_prompt("Enter Option"))
            self.handle_menu_selection(answer)
        except ValueError as e:
            self.cli.print_error(f"ERROR: {e}")
    
    def handle_menu_selection(self, selection):
        """
        Matches Selection to the function
        """
        match selection:
            case 1:
                AccountManager().main()
            case 2:
                # Trade Manager functionality can be implemented here
                config_manager.AccountSettings()
                pass
            case 3:
                self.whitelist_manager.main()
            case 4:
                self.start_trader()

    def queue_traders(self, roblox_account: RobloxAPI()):
        """
            This Should be ran in a thread and can be called to stop at any time.
            It uses the roblox account to scrape Roblox Owner API and checks if they arent in the cache
            It also checks if you can trade  with them and adds them into self.user_queue
        """
        try:
            while not self.stop_event.is_set():
                if len(self.user_queue) > 20:
                    #print("user queue is above 20")
                    time.sleep(40)
                    continue
                random_item = self.rolimons.return_item_to_scan()['item_id']

                owners=[]
                active_traders_response = roblox_account.get_active_traders(random_item, owners)
                if active_traders_response == None:
                    continue
                print("fetched new owners", owners, "\n","*"*30)


                for owner in owners:
                    if int(owner) in roblox_account.all_cached_traders:
                            print("already traded with player, skipping")
                            continue

                    print("checking if can trade")
                    roblox_account.all_cached_traders.add(owner)
                    if roblox_account.check_can_trade(owner):
                        print("can trade with", owner, "checking invetory..")
                        inventory = roblox_account.fetch_inventory(owner)
                        if inventory == False: 
                            continue
                        print("fetched inventory for", owner)
                        self.user_queue[owner] = inventory
                    time.sleep(.15) 
        except Exception as e:
            tb = traceback.format_exc()  # Capture the full traceback
            print(e, tb)
            with open("log.txt", "a") as log_file:
                log_file.write(f"Error in queue_traders: {e}, {tb}\n")


    def merge_lists(self, list1, list2):
        # Use set to merge and remove duplicates
        return list(set(list1) | set(list2))

    def update_data_thread(self):
        """
        Updates the table self.rolimons.data whenever rolimons updates
        """
        self.rolimons.update_data()      
        while True:
            if time.time() - self.last_updated_rolimons >= 120:
                self.last_updated_rolimons = time.time()
                self.rolimons.update_data()      

    def check_outbound_thread(self, roblox_accounts):
        def check_oubounds():
            for account in roblox_accounts:
                account.outbound_api_checker()
                account.check_completeds()

        check_oubounds()
        self.last_checked_trades = time.time()

        while True:
            if time.time() - self.last_checked_trades >= 1800:
                self.last_checked_trades = time.time()
                check_oubounds()
            time.sleep(5)

    def check_whitelist_timer(self):
        """
        Checks the whitelist in intervals
        """
        last_checked = time.time() - self.whitelist_checked
        if last_checked >= 600:
            self.whitelist_checked = time.time()
            validate = self.validate_whitelist()
            if validate != True:
                self.stop_event.set()  # Signal all threads to stop
                input("Whitelist check failed")
                return False

    def start_thread(self, thread:threading.Thread):
        thread.daemon = True
        thread.start()

    def start_trader(self):
        """
            Main Loop function that loops through all the accounts and run the traders
        """
        if not self.validate_whitelist():
            print("Whitelist not valid in starting")
            sys.exit()
            quit()
            return False
        roblox_accounts = self.load_roblox_accounts()
        self.start_thread(threading.Thread(target=self.check_outbound_thread, args=(roblox_accounts,)))
        self.start_thread(threading.Thread(target=self.update_data_thread))

        time.sleep(1)
        while True:
            if self.check_whitelist_timer() == False:
                sys.exit()
                quit()
                return False

            threads = []
            if roblox_accounts == []:
                input("No active accounts found!")
                break
            for current_account in roblox_accounts:

                if current_account.config.inbounds['CounterTrades'] == True:
                    try:
                        current_account.counter_trades()
                        last_checked = time.time() - current_account.counter_timer
                        if last_checked >= 1800:
                            print("countering")
                            current_account.counter_timer = time.time()
                            current_account.counter_trades()
                    except Exception as e:
                        print("starting countering error:",e )
                        pass

                if time.time() - current_account.last_generated_csrf_timer >= 900:
                    print("Refreshing csrf token")
                    current_account.request_handler.generate_csrf()

                current_account.last_sent_trade = time.time()
                # Check if all accounts are rate-limited
                # TODO: Make all accounts having no tradeable inventory as a check
                

                if current_account.config.debug['ignore_limit'] == False:
                    if self.json.is_all_ratelimited():
                        print("All cookies sent out 100 daily trades. Rechecking in 20 minutes...")
                        time.sleep(20 * 60)
                        break  # retry loop

                    if self.json.check_ratelimit_cookie(current_account.cookies['.ROBLOSECURITY']):
                        print(current_account.username, "Hit 100 trade limit continuing to next acc")
                        continue

                # Get inventory
                current_account.refresh_self_inventory()

                if not current_account.account_inventory:
                    print(current_account.username, "has no tradeable inventory")
                    time.sleep(5)
                    continue
                if current_account.check_premium(current_account.account_id) == False:
                    print(current_account.username, "is not premium")
                    time.sleep(5)
                    continue

                print("Continuing on", current_account.username)
                current_account.get_recent_traders()  

                print("Got recent traders")
                # TODO: add max days inactive in cfg and parse as arg

                # to make the threads run even after stop event is called and another thread starts
                print("startign queue thread")
                self.stop_event.clear()
                queue_thread = threading.Thread(target=self.queue_traders, args=(current_account,))
                queue_thread.daemon = True
                queue_thread.start()

                #threads.append((queue_thread))


                print("started queue thread, now processing trades")
                # After queuing, start processing trades for the account (is a while true)
                self.process_trades_for_account(current_account)

                #for thread in threads:
                #    thread.join()
                # Wait for all threads to finish before moving to next iteration
                print("Stopping threads...")
                self.stop_event.set()  # Signal all threads to stop
            time.sleep(5)


            # min overall 300
    def process_trades_for_account(self, account):
        """
            Generates and Starts trading for the given account
        """
        while True:
            try:
                account_inventory = account.account_inventory

                if self.check_whitelist_timer() == False:
                    sys.exit()
                    quit()
                # Check if user queue is empty
                while not self.user_queue:
                    time.sleep(10)

                #current_user_queue = self.user_queue.copy()
                
                print("Started trading...")

                if not account.account_inventory:
                    print('[Debug] process account inventory on hold breaking')
                    break

                for trader in list(self.user_queue.keys()):  # Using list() creates a copy of the keys
                    if time.time() - account.last_sent_trade > account.config.filter_generated['Max_Seconds_Spent_on_One_User']:
                        print("Couldnt find any trades for", account.username,  account.config.filter_generated['Max_Seconds_Spent_on_One_User'], "Seconds")
                        account.last_sent_trade = time.time()
                        return None
                    else:
                        print(time.time() - account.last_sent_trade, "time spent trying to find trades with", account.username)
                    print("trading with", trader)
                    trader_inventory = self.user_queue[trader]
                    
                        
                    # Delete the key from the dictionary
                    self.user_queue.pop(trader, None)  # Safely remove the key using pop
                    
                    # Generate and send trade if there are items to trade
                    if account_inventory and trader_inventory:
                        print("generating trade for", account.username)
                        generated_trade = account.trade_maker.generate_trade(account_inventory, trader_inventory)


                        if not generated_trade:
                            print("no generated trade for", account.username)
                            if not account.account_inventory:
                                print('[Debug] process account in trading inventory on hold returning')
                                return None
                            break

                        print(f"Generated trade: {generated_trade}", account.username)

                        # Extract trade details
                        self_side = generated_trade['self_side']
                        their_side = generated_trade['their_side']
                        self_robux = generated_trade['self_robux']

                        send_trade_response = account.send_trade(trader, self_side, their_side, self_robux=self_robux)

                        if account.config.debug['ignore_limit'] == False:
                            if send_trade_response == False:  # Rate-limited
                                print("Roblox account limited")
                                self.json.add_ratelimit_timestamp(account.cookies['.ROBLOSECURITY'])
                                return False

                        # Handle webhook
                        if send_trade_response:
                            account.last_sent_trade = time.time()
                            def get_duplicate_items(side: tuple, inventory: dict) -> list:
                                assetids = []
                                for asset_id in side:
                                    valid_item = inventory.get(asset_id)
                                    if valid_item:
                                        assetids.append(valid_item['item_id'])
                                return assetids

                            # Get duplicated item_ids from asset_ids
                            self_items = get_duplicate_items(self_side, account_inventory)
                            trader_items = get_duplicate_items(their_side, trader_inventory)

                            generated_trade['self_side_item_ids'] = self_items
                            generated_trade['their_side_item_ids'] = trader_items


                            embed_fields, total_profit = self.discord_webhook.embed_fields_from_trade(generated_trade, self.rolimons.item_data, self.rolimons.projected_json.read_data())

                            embed = self.discord_webhook.setup_embed(title=f"Sent a trade with {total_profit} total profit", color=1, user_id=trader, embed_fields=embed_fields, footer="Frick shedletsky")
                            self.discord_webhook.send_webhook(embed, "https://discord.com/api/webhooks/1311127129731108944/RNlwYAMpLH1tJmwSTNDfuFOb9id2EmfC9AEvwSu5Gh-RNKcze35Pnp8asRBGt7dRsUaI")                    # Send trade request
                            pass
                    else:
                        if not account_inventory:
                            print(account.username, "Doesn't have a tradeable inventory..")
                            break
            except Exception as e:
                tb = traceback.format_exc()  # Capture the full traceback
                print(e, tb)
                with open("log.txt", "a") as log_file:
                    log_file.write(f"Error in process trades: {e}, {tb}\n")



    def load_roblox_accounts(self):
        """
        Returns a list of Roblox Classes that were made from the cookie json
        """
        print("Loading roblox accounts...")
        cookie_json = self.json.read_data()
        roblox_accounts = []

        for account in cookie_json['roblox_accounts']:
            # Dont use account if its disabled
            if account['use_account'] == False:
                continue

            
            roblox_cookie = {'.ROBLOSECURITY': account['cookie']}
            auth_secret = account['auth_secret']
            last_completed = account['last_completed']
            user_id = account['user_id']

            # TODO: ADD CUSTOM CONFIG
                
                
            roblox_account = RobloxAPI(cookie=roblox_cookie, auth_secret=auth_secret)
            roblox_account.request_handler.generate_csrf()

            user_config = self.account_configs.get_config(user_id)
            if user_config:
                roblox_account.config.trading = user_config
            else:
                pass
            roblox_accounts.append(roblox_account)
        return roblox_accounts
    

if __name__ == "__main__":
    try:
        doggo = Doggo()
        if not doggo.validate_whitelist():
            print("Whitelist not valid")
            time.sleep(1)
            Doggo().whitelist_manager.main()
        doggo.main()

    except Exception as e:
        tb = traceback.format_exc()  # Capture the full traceback
        print(e, tb)
        with open("log.txt", "a") as log_file:
            log_file.write(f"Error in process trades: {e}, {tb}\n")
    finally:
        sys.exit()
        quit()



