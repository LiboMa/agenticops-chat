举一个简单例子的场景：

由ALB -> SG(EC2) lacking of rules X-> app:443 -> RDS

CW/datadog/prometheus -> Alert -> Chat Group -> Main Agents->SRE->fix paln -> excution and resolved -> report(SOP->KB)

就是伪造一个Alert 发送到Feishu Chat Group，Agent接收到告警，然后发起自修复，记录状态，并做Report