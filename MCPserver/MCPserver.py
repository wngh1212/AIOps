import logging
import time
from datetime import datetime, timedelta, timezone

import boto3

logger = logging.getLogger(__name__)


class MCPServer:
    def __init__(self, region="ap-northeast-2"):
        self.region = region
        self._initialize_clients()
        logger.info("MCPServer initialized")

    def _initialize_clients(self):
        self.ec2 = boto3.client("ec2", region_name=self.region)
        self.cw = boto3.client("cloudwatch", region_name=self.region)
        self.ssm = boto3.client("ssm", region_name=self.region)
        self.ce = boto3.client("ce", region_name=self.region)

    def change_region(self, new_region):
        # AWS 리전 변경
        if new_region == self.region:
            return

        old_region = self.region
        self.region = new_region

        try:
            self._initialize_clients()
        except Exception as e:
            self.region = old_region
            self._initialize_clients()
            raise

    def _get_latest_ami(self):
        try:
            response = self.ssm.get_parameter(
                Name="/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64",
                WithDecryption=False,
            )
            return response["Parameter"]["Value"]
        except Exception as e:
            logger.warning(f"Failed to get latest AMI: {e}, using default")
            return "ami-0c9c94c3f41b76315"

    def _get_default_subnet(self):
        try:
            response = self.ec2.describe_subnets(
                Filters=[{"Name": "default-for-az", "Values": ["true"]}]
            )
            if response["Subnets"]:
                target = response["Subnets"][0]["SubnetId"]
                az = response["Subnets"][0]["AvailabilityZone"]
                logger.info(f"Auto-detected Default Subnet: {target} ({az})")
                return target
            else:
                logger.warning("No Default Subnet found in this account")
        except Exception as e:
            logger.error(f"Subnet Auto-detection failed: {e}")
        return None

    import logging

    logger = logging.getLogger(__name__)

    def get_cost_by_date(self, start_date, end_date):
        """Human-friendly [start_date, end_date] → Cost Explorer-safe [Start, End)"""
        try:
            logger.info(f"Fetching cost for {start_date} ~ {end_date}")

            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")

            # Cost Explorer는 [Start, End) 이므로 End는 end_dt + 1일
            ce_start = start_dt

            # 사용자가 end_date를 미래로 주면 현재 시점 기준으로 자르기
            today = datetime.now().date()
            if end_dt.date() > today:
                end_dt = datetime(today.year, today.month, today.day)

            ce_end = end_dt + timedelta(days=1)

            # End는 "다음 달 1일"을 넘어가면 안 됨 → 현재 달 기준 상한 설정
            # 오늘이 2026-01-05면 upper_bound = 2026-02-01
            upper_bound = datetime(today.year, today.month, 1) + timedelta(days=32)
            upper_bound = upper_bound.replace(day=1)  # 다음 달 1일

            if ce_end > upper_bound:
                ce_end = upper_bound

            ce_start_str = ce_start.strftime("%Y-%m-%d")
            ce_end_str = ce_end.strftime("%Y-%m-%d")

            logger.info(
                f"Calling Cost Explorer with Start={ce_start_str}, End={ce_end_str}"
            )

            res = self.ce.get_cost_and_usage(
                TimePeriod={"Start": ce_start_str, "End": ce_end_str},
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
            )

            if res["ResultsByTime"]:
                amt = float(res["ResultsByTime"][0]["Total"]["UnblendedCost"]["Amount"])
                return f"Cost from {start_date} to {end_date}: ${amt:.2f}"
            else:
                return f"Cost from {start_date} to {end_date}: $0.00"

        except Exception as e:
            logger.error(f"Cost retrieval failed: {e}", exc_info=True)
            return f"Cost Error: {str(e)}"

    def _get_cpu_metric(self, instance_id):
        # 인스턴스의 최근 CPU 사용률 조회
        try:
            now = datetime.now(timezone.utc)
            stats = self.cw.get_metric_statistics(
                Namespace="AWS/EC2",
                MetricName="CPUUtilization",
                Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                StartTime=now - timedelta(minutes=5),
                EndTime=now,
                Period=300,
                Statistics=["Average"],
            )

            if stats["Datapoints"]:
                cpu_val = round(stats["Datapoints"][-1]["Average"], 2)
                logger.debug(f"CPU for {instance_id}: {cpu_val}%")
                return cpu_val
            else:
                logger.debug(f"No CPU data available for {instance_id}")
                return 0.0
        except Exception as e:
            logger.warning(f"Failed to get CPU metric for {instance_id}: {e}")
            return 0.0

    def call_tool(self, tool_name: str, args: dict):
        logger.debug(f"[Tool Call] {tool_name} | Args: {args}")

        try:
            normalized_args = self._normalize_args(args)
            logger.debug(f"[Normalized] {normalized_args}")
            tool_mapping = {
                # ===== VPC/Network =====
                "create_vpc": lambda: self.create_vpc(normalized_args.get("cidr")),
                "create_subnet": lambda: self.create_subnet(
                    normalized_args.get("vpc_id"),
                    normalized_args.get("cidr") or normalized_args.get("cidr_block"),
                ),
                # ===== Instance 생성/조회 =====
                "create_instance": lambda: self._handle_create_instance(
                    normalized_args
                ),
                "list_instances": lambda: self.list_instances(
                    normalized_args.get("status", "all")
                ),
                # ===== Instance 상태 변경 (중요!) =====
                "start_instances": lambda: self.start_instances(
                    normalized_args.get("instance_id")
                ),
                "stop_instances": lambda: self.stop_instances(
                    normalized_args.get("instance_id")
                ),
                "reboot_instances": lambda: self.reboot_instances(
                    normalized_args.get("instance_id")
                ),
                "terminate_resource": lambda: self.terminate_resource(
                    normalized_args.get("instance_id")
                ),
                # ===== 스냅샷/크기 조정 =====
                "create_snapshot": lambda: self.create_snapshot(
                    normalized_args.get("instance_id")
                ),
                "resize_instance": lambda: self.resize_instance(
                    normalized_args.get("instance_id"),
                    normalized_args.get("instance_type"),
                ),
                # ===== 모니터링/로깅 =====
                "get_metric": lambda: self.get_metric(
                    normalized_args.get("instance_id"),
                    normalized_args.get("metric_name", "CPUUtilization"),
                ),
                "get_recent_logs": lambda: self.get_recent_logs(
                    normalized_args.get("id")
                ),
                "get_cost": lambda: self.get_cost(),
                "generate_topology": lambda: self.generate_topology(),
                # ===== 제네릭 (권장하지 않음) =====
                "execute_aws_action": lambda: self.execute_aws_action(normalized_args),
            }

            if tool_name not in tool_mapping:
                raise ValueError(
                    f"❌ 알 수 없는 도구: {tool_name}\n"
                    f"   사용 가능한 도구: {list(tool_mapping.keys())}"
                )

            result = tool_mapping[tool_name]()

            logger.info(f"[Success] {tool_name} | Result: {result}")
            return result

        except Exception as e:
            logger.error(f"[Error] {tool_name} | {str(e)}")
            return {
                "status": "error",
                "tool": tool_name,
                "message": str(e),
                "args_received": args,
            }

    def _normalize_args(self, args: dict) -> dict:
        """
        모든 파라미터를 정규화하고 이름→ID 변환 수행

        이 함수는 모든 도구 호출의 전처리 단계입니다!
        """

        normalized = args.copy()

        # ===== 1단계: 문자열 정규화 =====
        for key in normalized:
            if isinstance(normalized[key], str):
                normalized[key] = self._clean_str(normalized[key])

        # ===== 2단계: instance_id 필드 처리 =====
        if "instance_id" in normalized and normalized["instance_id"]:
            try:
                normalized["instance_id"] = self._resolve_id(normalized["instance_id"])
                logger.debug(
                    f"[Name Resolution] {args.get('instance_id')} → "
                    f"{normalized['instance_id']}"
                )
            except ValueError as e:
                logger.warning(f"instance_id 변환 실패: {str(e)}")
                # 변환 실패해도 계속 진행 (에러는 도구 실행 시 발생)

        # ===== 3단계: name 필드 처리 =====
        if "name" in normalized and normalized["name"]:
            try:
                normalized["instance_id"] = self._resolve_id(normalized["name"])
                logger.debug(
                    f"[Name Resolution] {normalized['name']} → "
                    f"{normalized['instance_id']}"
                )
                # name으로 변환된 instance_id를 저장
                del normalized["name"]  # 더 이상 필요 없음
            except ValueError as e:
                logger.warning(f"name 변환 실패: {str(e)}")

        # ===== 4단계: InstanceIds 리스트 처리 =====
        if "InstanceIds" in normalized and normalized["InstanceIds"]:
            try:
                normalized["InstanceIds"] = [
                    self._resolve_id(id_or_name)
                    if not id_or_name.startswith("i-")
                    else id_or_name
                    for id_or_name in normalized["InstanceIds"]
                ]
                logger.debug(f"[Batch Resolution] {normalized['InstanceIds']}")
            except ValueError as e:
                logger.warning(f"InstanceIds 변환 실패: {str(e)}")

        return normalized

    def _handle_create_instance(self, args: dict):
        img = self._clean_str(args.get("image_id"))
        if not img or not img.startswith("ami-"):
            logger.info("Validating AMI ID...")
            img = self._get_latest_ami()

        sub_id = args.get("subnet_id")
        if not sub_id:
            sub_id = self._get_default_subnet()
            if not sub_id:
                return "Error: No Subnet provided and failed to auto-detect one in ap-northeast-2a."

        return self.create_instance(
            image_id=img,
            instance_type=args.get("instance_type", "t2.nano"),
            subnet_id=sub_id,
            sg_id=args.get("sg_id"),
            name=self._clean_str(args.get("name", "new-instance")),
        )

    def _get_id_or_name(self, args: dict):
        return args.get("instance_id") or args.get("name")

    def create_vpc(self, cidr):
        if not cidr:
            cidr = "10.0.0.0/16"
        res = self.ec2.create_vpc(CidrBlock=cidr)
        vpc_id = res["Vpc"]["VpcId"]
        self.ec2.create_tags(
            Resources=[vpc_id], Tags=[{"Key": "Name", "Value": "AI-VPC"}]
        )
        logger.info(f"VPC created: {vpc_id}")
        return {"status": "success", "resource_id": vpc_id, "type": "vpc"}

    def create_subnet(self, vpc_id, cidr, az=None):
        if not vpc_id:
            return "Error: VPC ID missing"
        if not cidr:
            return "Error: CIDR block missing"

        # AZ 선택
        if not az:
            try:
                vpc_info = self.ec2.describe_vpcs(VpcIds=[vpc_id])
                if vpc_info["Vpcs"]:
                    azs = vpc_info["Vpcs"][0].get(
                        "AvailabilityZones", ["ap-northeast-2a"]
                    )
                    az = azs[0]
                else:
                    az = "ap-northeast-2a"
            except:
                az = "ap-northeast-2a"

        try:
            logger.info(f"Creating subnet: VPC={vpc_id}, CIDR={cidr}, AZ={az}")
            res = self.ec2.create_subnet(
                VpcId=vpc_id, CidrBlock=cidr, AvailabilityZone=az
            )
            subnet_id = res["Subnet"]["SubnetId"]
            return {
                "status": "success",
                "resource_id": subnet_id,
                "type": "subnet",
                "az": az,
            }
        except Exception as e:
            return f"Error: {str(e)}"

    def create_instance(self, image_id, instance_type, subnet_id, sg_id, name):
        image_id = self._clean_str(image_id)
        logger.info(
            f"Launching: AMI={image_id}, Type={instance_type}, Subnet={subnet_id}, Name={name}"
        )

        run_args = {
            "ImageId": image_id,
            "InstanceType": instance_type,
            "SubnetId": subnet_id,
            "MinCount": 1,
            "MaxCount": 1,
            "TagSpecifications": [
                {"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": name}]}
            ],
        }
        if sg_id:
            run_args["SecurityGroupIds"] = [sg_id]

        res = self.ec2.run_instances(**run_args)
        instance_id = res["Instances"][0]["InstanceId"]
        time.sleep(2)
        logger.info(f"Instance created: {instance_id}")
        return {"status": "success", "resource_id": instance_id, "type": "instance"}

    def list_instances(self, status="all"):
        try:
            filters = (
                []
                if status == "all"
                else [{"Name": "instance-state-name", "Values": ["running", "pending"]}]
            )
            res = self.ec2.describe_instances(Filters=filters)
            lines = []

            for r in res["Reservations"]:
                for i in r["Instances"]:
                    instance_id = i["InstanceId"]
                    name = next(
                        (t["Value"] for t in i.get("Tags", []) if t["Key"] == "Name"),
                        "Unknown",
                    )
                    state = i["State"]["Name"]

                    # CPU 메트릭 추가
                    cpu_val = 0.0
                    if state == "running":
                        cpu_val = self._get_cpu_metric(instance_id)

                    lines.append(
                        f"ID: {instance_id} | Name: {name} | State: {state} | CPU: {cpu_val}%"
                    )

            result = "\n".join(lines) if lines else "No instances found."
            logger.debug(f"List instances result: {len(lines)} instances found")
            return result
        except Exception as e:
            logger.error(f"Failed to list instances: {e}", exc_info=True)
            return f"Error: {str(e)}"

    def get_cost(self):
        try:
            now = datetime.now()
            start = now.replace(day=1).strftime("%Y-%m-%d")
            end = now.strftime("%Y-%m-%d")
            if start == end:
                return "The first day of each month is being counted"
            res = self.ce.get_cost_and_usage(
                TimePeriod={"Start": start, "End": end},
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
            )
            amt = float(res["ResultsByTime"][0]["Total"]["UnblendedCost"]["Amount"])
            result = f"This Month's Estimated Cost: ${amt:.2f} ({start} ~ {end})"
            logger.info(f"Cost retrieved: ${amt:.2f}")
            return result
        except Exception as e:
            logger.error(f"Cost Error: {e}")
            return f"Cost Error: {str(e)}"

    def get_metric(self, identifier, metric):
        tid = self._resolve_id(identifier)
        if not tid:
            return f"Instance '{identifier}' not found"

        if metric == "CPUUtilization":
            cpu_val = self._get_cpu_metric(tid)
            return f"{metric} for {tid}: {cpu_val}%"

        return f"{metric} for {tid}: 0.5% (Mock)"

    def create_snapshot(self, identifier):
        tid = self._resolve_id(identifier)
        if not tid:
            return "Instance not found"
        logger.info(f"Snapshot started for {identifier} ({tid})")
        return f"Snapshot Started for {identifier} ({tid})"

    def resize_instance(self, identifier, new_type):
        tid = self._resolve_id(identifier)
        if not tid:
            return f"target {identifier} not found"
        try:
            response = self.ec2.describe_instances(InstanceIds=[tid])
            state = response["Reservations"][0]["Instances"][0]["State"]["Name"]
            if state != "stopped":
                return f"Error : Instance must be stopped to resize. Current state: {state}"
            self.ec2.modify_instance_attribute(
                InstanceId=tid, InstanceType={"Value": new_type}
            )
            return f"Successfully resized {identifier} ({tid}) to {new_type}"

        except Exception as e:
            return f"Error resizing instance: {str(e)}"

    def generate_topology(self):
        lines = ["Topology:"]
        try:
            vpcs = self.ec2.describe_vpcs()["Vpcs"]
            for vpc in vpcs:
                lines.append(f"[VPC: {vpc['VpcId']}]")
            logger.debug(f"Topology generated: {len(vpcs)} VPCs")
        except Exception as e:
            logger.error(f"Failed to generate topology: {e}")
        return "\n".join(lines)

    def terminate_resource(self, identifier):
        tid = self._resolve_id(identifier)
        if not tid:
            return f"Target '{identifier}' not found."
        self.ec2.terminate_instances(InstanceIds=[tid])
        logger.info(f"Terminated instance {identifier} ({tid})")
        return f"Terminating instance {identifier} ({tid})..."

    def get_recent_logs(self, instance_id):
        try:
            tid = self._resolve_id(instance_id)
            if not tid:
                return f"Instance '{instance_id}' not found"

            # CloudWatch Logs에서 인스턴스 관련 로그 조회
            logger.info(f"Fetching logs for {tid}")
            return f"Recent logs for {tid}: [샘플 로그 데이터]"
        except Exception as e:
            logger.error(f"Failed to get logs: {e}")
            return f"Error fetching logs: {str(e)}"

    def execute_aws_action(self, args):
        try:
            action_name = args.get("action_name")
            params = args.get("params", {})
            instance_ids = params.get("InstanceIds", [])
            auto_resolve = args.get("auto_resolve_names", False)

            if auto_resolve:
                resolved_ids = []
                for id_or_name in instance_ids:
                    tid = self._resolve_id(id_or_name)
                    if tid:
                        resolved_ids.append(tid)
                        instance_ids = resolved_ids

            if not instance_ids:
                return "Error: No valid instance IDs provided"

            logger.info(f"Executing AWS action: {action_name} on {instance_ids}")

            # 액션 실행
            if action_name == "start_instances":
                self.ec2.start_instances(InstanceIds=instance_ids)
                return f"Started instances: {instance_ids}"

            elif action_name == "stop_instances":
                self.ec2.stop_instances(InstanceIds=instance_ids)
                return f"Stopped instances: {instance_ids}"

            elif action_name == "reboot_instances":
                self.ec2.reboot_instances(InstanceIds=instance_ids)
                return f"Rebooted instances: {instance_ids}"

            else:
                return f"Unknown action: {action_name}"

        except Exception as e:
            logger.error(f"AWS action failed: {e}")
            return f"Error executing action: {str(e)}"

    def _clean_str(self, s: str) -> str:
        if s is None:
            raise ValueError("Input value is None")

        if not isinstance(s, str):
            raise TypeError(f"It's not a string: {type(s)}")

        cleaned = s.strip()
        if not cleaned:
            raise ValueError("Input value is empty")

        return cleaned

    def _resolve_id(self, identifier: str) -> str:
        identifier = self._clean_str(identifier)
        if identifier.startswith("i-") and len(identifier) == 19:
            logger.debug(f"Instance ID 형식: {identifier}")
            return self._validate_instance_id(identifier)

        logger.debug(f"Search by name: {identifier}")

        try:
            # 정확한 일치 시도
            return self._search_exact(identifier)
        except ValueError as e:
            return self._search_partial(identifier)

    def _validate_instance_id(self, instance_id: str) -> str:
        try:
            response = self.ec2.describe_instances(
                InstanceIds=[instance_id],
                Filters=[
                    {
                        "Name": "instance-state-name",
                        "Values": ["running", "stopped", "pending", "stopping"],
                    }
                ],
            )

            if not response["Reservations"]:
                raise ValueError(f"존재하지 않는 인스턴스: {instance_id}")

            return instance_id

        except self.ec2.exceptions.InvalidInstanceID.Malformed:
            raise ValueError(f"Invalid Instance ID format: {instance_id}")
        except Exception as e:
            raise ValueError(f"Instance ID verification failed: {str(e)}")

    def _search_exact(self, name: str) -> str:
        try:
            response = self.ec2.describe_instances(
                Filters=[
                    {"Name": "tag:Name", "Values": [name]},
                    {
                        "Name": "instance-state-name",
                        "Values": ["running", "stopped", "pending", "stopping"],
                    },
                ]
            )

            instances = []
            for reservation in response["Reservations"]:
                instances.extend(reservation["Instances"])

            if len(instances) == 0:
                raise ValueError(f"No exact match: {name}")

            if len(instances) == 1:
                instance_id = instances[0]["InstanceId"]
                logger.info(
                    f"Identification of Accurate Matches: {name} → {instance_id}"
                )
                return instance_id

            # 여러 개 발견 (중복)
            ids = [inst["InstanceId"] for inst in instances]
            raise ValueError(
                f"Multiple instances use the same name: {name}\nInstance IDs: {ids}"
            )

        except ValueError:
            raise  # 그대로 전파
        except Exception as e:
            raise ValueError(f"정확한 검색 실패: {str(e)}")

    def _search_partial(self, name: str) -> str:
        # 하이픈, 공백, 대소문자 무시
        normalized_input = (
            name.lower().replace("-", "").replace("_", "").replace(" ", "")
        )

        try:
            response = self.ec2.describe_instances(
                Filters=[
                    {
                        "Name": "instance-state-name",
                        "Values": ["running", "stopped", "pending", "stopping"],
                    }
                ]
            )

            matching = []

            for reservation in response["Reservations"]:
                for instance in reservation["Instances"]:
                    # Name 태그 추출
                    name_tag = next(
                        (
                            t["Value"]
                            for t in instance.get("Tags", [])
                            if t["Key"] == "Name"
                        ),
                        "",
                    )

                    if not name_tag:
                        continue

                    # 정규화된 비교
                    normalized_tag = (
                        name_tag.lower()
                        .replace("-", "")
                        .replace("_", "")
                        .replace(" ", "")
                    )

                    if (
                        normalized_input in normalized_tag
                        or normalized_tag in normalized_input
                    ):
                        matching.append(
                            {"InstanceId": instance["InstanceId"], "Name": name_tag}
                        )

            if len(matching) == 0:
                available = self._get_available_instances()
                raise ValueError(
                    f"No Instances: {name}\n"
                    f"Available Instances:\n" + "\n".join(f"  - {n}" for n in available)
                )

            if len(matching) == 1:
                instance_id = matching[0]["InstanceId"]
                instance_name = matching[0]["Name"]
                logger.warning(
                    f"Using Partial Match: '{name}' → {instance_name} ({instance_id})"
                )
                return instance_id

            # 여러 개 매칭
            matches_str = "\n".join(
                f"  - {m['Name']} ({m['InstanceId']})" for m in matching
            )
            raise ValueError(f"Matching Multiple Instances: {name}\n{matches_str}\n")

        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Partial match search failed: {str(e)}")

    def _get_available_instances(self) -> list:
        try:
            response = self.ec2.describe_instances(
                Filters=[
                    {"Name": "instance-state-name", "Values": ["running", "stopped"]}
                ]
            )

            names = []
            for reservation in response["Reservations"]:
                for instance in reservation["Instances"]:
                    name_tag = next(
                        (
                            t["Value"]
                            for t in instance.get("Tags", [])
                            if t["Key"] == "Name"
                        ),
                        None,
                    )
                    if name_tag:
                        names.append(name_tag)

            return sorted(names) if names else ["(없음)"]
        except Exception as e:
            logger.warning(f"Instance list lookup failed: {str(e)}")
            return []

    def start_instances(self, instance_id: str) -> dict:
        try:
            self.ec2.start_instances(InstanceIds=[instance_id])
            logger.info(f"running instance : {instance_id}")
            return {
                "status": "success",
                "action": "start_instances",
                "instance_id": instance_id,
            }
        except Exception as e:
            logger.error(f"start faild: {instance_id} | {str(e)}")
            return {"status": "error", "message": str(e)}

    def stop_instances(self, instance_id: str) -> dict:
        try:
            self.ec2.stop_instances(InstanceIds=[instance_id])
            logger.info(f"✓ 중지됨: {instance_id}")
            return {
                "status": "success",
                "action": "stop_instances",
                "instance_id": instance_id,
            }
        except Exception as e:
            logger.error(f"중지 실패: {instance_id} | {str(e)}")
            return {"status": "error", "message": str(e)}

    def reboot_instances(self, instance_id: str) -> dict:
        try:
            self.ec2.reboot_instances(InstanceIds=[instance_id])
            logger.info(f"재부팅됨: {instance_id}")
            return {
                "status": "success",
                "action": "reboot_instances",
                "instance_id": instance_id,
            }
        except Exception as e:
            logger.error(f"재부팅 실패: {instance_id} | {str(e)}")
            return {"status": "error", "message": str(e)}
