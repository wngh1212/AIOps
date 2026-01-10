# AIOps: AWS Autonomous Operations Agent

본 프로젝트는 LLM의 추론 능력과 엔지니어의 통제권을 결합한 지능형 Assisted Ops 시스템을 구현하기 위한 프로젝트 입니다
AWS 클라우드 인프라를 자연어로 관리하고 장애 발생 시 SOP에 기반하여 최적의 복구 액션을 제안 및 실행할 수 있는 기능을 가지고 있습니다
<img width="1024" height="559" alt="image" src="https://github.com/user-attachments/assets/e32b4fa4-77ae-42ff-ae0d-1f49aef4fcc9" />

## SRE Principle

**Assisted Ops**: AI에게 파괴적인 권한을 무조건 위임하는 대신 엔지니어의 의사결정을 돕고 실행을 자동화하여 시스템의 안정성을 확보

**Recovery First**: 근본 원인 분석에 매몰되기보다 서비스 정상화를 최우선 액션으로 도출하도록 지능을 설계
 
**Structured Control**: LLM과의 통신에 JSON 형식을 강제하여 할루시네이션 발생 확률을 물리적으로 억제



---

## 시스템 아키텍처

 **MCP** 기반의 모듈형 구조로 설계

* **`ChatOpsClient` (`agent/aiOps.py`)**: 사용자 의도를 분석하고 도구를 매핑하는 두뇌 역할을 수행
* **`MCPServer` (`MCPserver/MCPserver.py`)**: Boto3를 통해 실제 AWS 리소스를 제어하는 하위 인터페이스
* **`MonitorAgent` (`agent/monitor.py`)**: 인프라 상태를 30초 주기로 감시하며 장애를 감지
* **`SOPManager` (`Utils/sop_manager.py`)**: ChromaDB(Vector DB)를 사용하여 장애 대응 가이드를 시맨틱 검색

---

## 주요 기능

### 1. 지능형 인프라 제어

* **자연어 명령 처리**: "웹 서버 시작해줘"와 같은 명령을 인식하여 `start_instances` 도구를 호출
* **리소스 자동 식별**: 인스턴스 ID를 직접 입력하지 않아도 'Name' 태그를 기반으로 대상을 추론하여 식별
* *English Native**: 추론 속도와 정확도 극대화를 위해 내부적으로는 BPE 효율이 높은 영어 기반 추론을 수행



### 2. 장애 감지 및 자가 복구

* **티어링 알람**: 장애 심각도에 따라 Tier 0(Emergency), Tier 1(Critical)으로 분류하여 Slack으로 전파
* **Semantic Fallback**: AI가 생성한 JSON 포맷에 오류가 있더라도 텍스트 내 키워드(REBOOT, START 등)를 재검색하여 작업을 완수

### 3. 안전 및 보안 (Safety First)

* **Critical Action 승인**: 인스턴스 삭제(`terminate`), 정지(`stop`) 등 위험 작업 시 엔지니어의 수동 승인 단계를 거침
* **명령어 필터링**: 시스템에 치명적인 영향을 줄 수 있는 명령어 실행을 원천 차단

---

## 기술

* **Language**: Python 3.x
* **LLM**: Llama
* **Cloud API**: AWS Boto3 (EC2, CloudWatch, Logs, CE)
* **Database**: ChromaDB (Vector Storage for SOP)
* **Framework**: LangChain Ollama

---

## 시작하기

### 1. 사전 요구 사항

* [Ollama](https://ollama.ai/) 설치 및  모델 다운로드 (필요에 따른 모델 교체 가능)
* AWS CLI 설정 (Credential 및 Region 필수)
* Python 패키지 설치: `pip install -r requirements.txt`

### 2. 실행

```bash
python main.py

```

### 3. 주요 명령어

* `auto on`: 인프라 감시 모니터 가동
* `auto off`: 모니터링 종료
* `exit`: 시스템 종료
* 일반 채팅: "List all instances", "Show me the monthly cost" 등

---

## 정보

**작성자**: 강주호 (가천대학교 게임영상학과) 

**소속**: 가천대학교 2025학년도 겨울 계절학기 개인 프로젝트 

---
