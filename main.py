import logging
import os
import sys
import threading
import time
from http.client import CONTINUE

from dotenv import load_dotenv
from langchain_ollama import OllamaLLM

from agent.aiOps import ChatOpsClient
from agent.monitor import MonitorAgent
from MCPServer.MCPserver import MCPServer

load_dotenv()
SLACK_WEBHOOK_URL = os.getenv("Slack_API_Key")
use_model_name = "llama3.2:3b"
AVAILABLE_REGIONS = [
    "us-east-1",  # N. Virginia 미국
    "us-east-2",  # Ohio 미국
    "us-west-1",  # N. California 미국
    "us-west-2",  # Oregon 미국
    "eu-west-1",  # Ireland 유럽
    "eu-central-1",  # Frankfurt 유럽
    "ap-northeast-1",  # Tokyo 일본
    "ap-northeast-2",  # Seoul 한국 ← 기본값
    "ap-southeast-1",  # Singapore 싱가포르
    "ap-southeast-2",  # Sydney 호주
    "ap-south-1",  # Mumbai 인도
    "ca-central-1",  # Canada 캐나다
]

CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"


def print_banner(current_region):
    # ANSI Color Codes

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
        f"   {GREEN}●{RESET} LLM Engine    : {YELLOW}{use_model_name}(Model changeable){RESET}"
    )
    print(f"   {GREEN}●{RESET} MCP Server    : {CYAN}Active{RESET}")
    print(f"   {GREEN}●{RESET} Language Mode : {GREEN}English Native{RESET}")
    print(f"   {GREEN}●{RESET} AWS Region    : {YELLOW}{current_region}{RESET}")

    print(
        f"{DIM}   ------------------------------------------------------------{RESET}"
    )
    print(f"{YELLOW}   [COMMANDS]{RESET}")
    print(f"   - {BOLD}auto on / off{RESET}       : Toggle Self-Healing Monitor")
    print(f"   - {BOLD}exit{RESET}                : Shutdown System")
    print(
        f"{DIM}   ------------------------------------------------------------{RESET}"
    )


def select_region():
    print(f"\n{BOLD}{CYAN}[REGION SELECTION]{RESET}")
    print(f"{YELLOW}Available AWS Regions:{RESET}")

    for idx, region in enumerate(AVAILABLE_REGIONS, 1):
        if region == "ap-northeast-2":
            print(f"  {idx:2d}. {region} {YELLOW}(Default){RESET}")
        else:
            print(f"  {idx:2d}. {region}")

    while True:
        try:
            choice = input(
                f"\n{CYAN}Select region number (1-{len(AVAILABLE_REGIONS)}) or name [default: ap-northeast-2]: {RESET}"
            ).strip()

            if not choice:
                return "ap-northeast-2"

            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(AVAILABLE_REGIONS):
                    return AVAILABLE_REGIONS[idx]
                else:
                    print(f"{YELLOW}❌ Invalid number. Try again.{RESET}")
                    continue

            if choice in AVAILABLE_REGIONS:
                return choice

            print(f"{YELLOW}❌ Invalid region. Try again.{RESET}")

        except KeyboardInterrupt:
            print(f"\n{YELLOW}Using default: ap-northeast-2{RESET}")
            return "ap-northeast-2"


def change_region(server, current_region):
    print(f"\n{BOLD}{CYAN}[REGION CHANGE]{RESET}")
    print(f"{YELLOW}Current Region: {current_region}{RESET}")
    print(f"{YELLOW}Available Regions:{RESET}")

    for idx, region in enumerate(AVAILABLE_REGIONS, 1):
        marker = " (current)" if region == current_region else ""
        print(f"  {idx:2d}. {region}{marker}")

    while True:
        try:
            choice = input(f"\n{CYAN}Select region number or name: {RESET}").strip()

            if not choice:
                print(f"{YELLOW}Cancelled.{RESET}")
                return current_region

            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(AVAILABLE_REGIONS):
                    new_region = AVAILABLE_REGIONS[idx]
                    break
                else:
                    print(f"{YELLOW}❌ Invalid number.{RESET}")
                    continue

            if choice in AVAILABLE_REGIONS:
                new_region = choice
                break

            print(f"{YELLOW}❌ Invalid region.{RESET}")

        except KeyboardInterrupt:
            print(f"\n{YELLOW}Cancelled.{RESET}")
            return current_region

    if new_region == current_region:
        print(f"{YELLOW}Already using {current_region}{RESET}")
        return current_region

    try:
        server.change_region(new_region)
        print(f"\n{GREEN}✓ Region changed to {new_region}{RESET}")
        return new_region
    except Exception as e:
        print(f"{YELLOW}Failed: {e}{RESET}")
        return current_region


def main():
    global monitoring_thread  # 전역 변수로 선언
    current_region = select_region()
    print_banner(current_region)
    print("\nInitializing Systems...", end="", flush=True)
    time.sleep(0.5)
    print("\rSystem Ready. Waiting for input.\n")
    try:
        server = MCPServer()
        llm = OllamaLLM(model=use_model_name)

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

            if user_input.lower() == "region":
                new_region = change_region(server, current_region)
                if new_region != current_region:
                    current_region = new_region
                    print(f"Now operating region{current_region}")
                continue

            if user_input.lower() == "exit":
                print("\n\033[91mShutting down system...\033[0m")
                if monitor_agent.is_running:
                    monitor_agent.stop_monitoring()

                if "monitoring_thread" in globals() and monitoring_thread:
                    monitoring_thread.join(timeout=5)
                break

            elif user_input.lower() == "auto on":
                if not monitor_agent.is_running:
                    print("\n\033[92m[AUTO] Self-Healing Monitor ENABLED\033[0m")
                    monitoring_thread = threading.Thread(
                        target=monitor_agent.start_monitoring,
                        args=(30,),
                        name="MonitoringAgent",
                        daemon=False,  # ← daemon=False로 변경
                    )
                    monitoring_thread.start()
                else:
                    print("Monitoring is already running.")

            elif user_input.lower() == "auto off":
                print("\n\033[93m[AUTO] Self-Healing Monitor DISABLED\033[0m")
                monitor_agent.stop_monitoring()
                if "monitoring_thread" in globals() and monitoring_thread:
                    monitoring_thread.join(timeout=3)

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
