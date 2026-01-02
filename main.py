import os
import sys
import threading
import time

from dotenv import load_dotenv
from langchain_ollama import OllamaLLM

from agent.aiOps import ChatOpsClient
from agent.monitor import MonitorAgent
from MCPServer.MCPserver import MCPServer

load_dotenv()
SLACK_WEBHOOK_URL = os.getenv("Slack_API_Key")


def print_banner():
    # ANSI Color Codes
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    logo = r"""
    ___    ____ ____
   /   |  /  _// __ \____  _____
  / /| |  / / / / / / __ \/ ___/
 / ___ |_/ / / /_/ / /_/ (__  )
/_/  |_/___/ \____/ .___/____/
                 /_/
    """

    print(CYAN + logo + RESET)
    print(f"{BOLD} AWS Autonomous Operations Agent {RESET}")
    print(
        f"{DIM}   ------------------------------------------------------------{RESET}"
    )
    print(f"   {GREEN}●{RESET} System Status : {GREEN}ONLINE{RESET}")
    print(
        f"   {GREEN}●{RESET} LLM Engine    : {YELLOW}Llama2:7b(Model changeable){RESET}"
    )
    print(f"   {GREEN}●{RESET} MCP Server    : {CYAN}Active{RESET}")
    print(f"   {GREEN}●{RESET} Language Mode : {GREEN}English Native{RESET}")
    print(
        f"{DIM}   ------------------------------------------------------------{RESET}"
    )
    print(f"{YELLOW}   [COMMANDS]{RESET}")
    print(f"   - {BOLD}auto on / off{RESET}       : Toggle Self-Healing Monitor")
    print(f"   - {BOLD}exit{RESET}                : Shutdown System")
    print(
        f"{DIM}   ------------------------------------------------------------{RESET}"
    )


def main():
    print_banner()

    print("\nInitializing Systems...", end="", flush=True)
    time.sleep(0.5)
    print("\rSystem Ready. Waiting for input.\n")

    try:
        server = MCPServer()
        llm = OllamaLLM(model="llama2:7b")

        # Chat 클라이언트 초기화
        chat_client = ChatOpsClient(server, llm)

        monitor_agent = MonitorAgent(server, llm, slack_url=SLACK_WEBHOOK_URL)

    except Exception as e:
        print(f"\n\033[91m❌ Critical Error during initialization: {e}\033[0m")
        return

    while True:
        try:
            user_input = input(f"\n\033[96m[CHAT] >>\033[0m ").strip()

            if not user_input:
                continue

            if user_input.lower() == "exit":
                print("\n\033[91mShutting down system...\033[0m")
                monitor_agent.stop_monitoring()
                break

            elif user_input.lower() == "auto on":
                if not monitor_agent.is_running:
                    print("\n\033[92m[AUTO] Self-Healing Monitor ENABLED\033[0m")
                    t = threading.Thread(
                        target=monitor_agent.start_monitoring, args=(30,)
                    )
                    t.daemon = True
                    t.start()
                    time.sleep(0.5)
                else:
                    print("Monitoring is already running.")

            elif user_input.lower() == "auto off":
                print("\n\033[93m[AUTO] Self-Healing Monitor DISABLED\033[0m")
                monitor_agent.stop_monitoring()

            else:
                # 일반 대화 및 명령 처리
                response = chat_client.chat(user_input)
                print(response)

        except KeyboardInterrupt:
            print("\n\n\033[91mForce Shutdown initiated.\033[0m")
            break
        except Exception as e:
            print(f"\033[91m❌ Error: {e}\033[0m")


if __name__ == "__main__":
    main()
