# Kexin-Multi-Exit-Proxy-Simulation

# Modules
- Proxy_Reachability_Testing [test_proxies.py.py](test_proxies.py.py)   
This module implements a concurrent proxy reachability testing tool for Clash-style configurations.  
It parses proxy lists, performs TCP connectivity checks, and filters unreachable nodes efficiently.  
The script supports parallel execution and outputs structured JSON reports for further analysis.

- Multi_Exit_Routing_Simulation (`double_ip.py`)
This module simulates multi-exit network routing by mapping multiple local proxy ports to different outbound nodes.  
It launches parallel browser instances using Playwright, each routed through a separate proxy, enabling real-time verification of exit IP behavior. The system supports headless mode, fast-loading optimizations, and configurable multi-port experiments.

# Core Framework
- Sing-box Configuration (`config.json`)
This configuration defines multiple inbound proxy ports and maps them to different outbound nodes.  
It enables local multi-port routing and serves as the foundation for multi-exit simulation experiments.

# Data & Results
- Proxy_Test_Results (`proxies_report.json`)
This file contains the output of proxy connectivity testing, including server reachability status.  
It can be used for filtering valid nodes and analyzing proxy reliability across regions.

# External Dependencies & Credits

- sing-box (Proxy Engine)
This project builds upon the open-source sing-box framework, which provides the underlying proxy routing capabilities.  
GitHub: https://github.com/SagerNet/sing-box  

- Public Proxy Nodes (Testing Data Source)
Proxy nodes used in this project are sourced from publicly available repositories for testing and experimentation purposes.  
GitHub: https://github.com/Barabama/FreeNodes  

# Notes
- This project focuses on system integration and network experimentation rather than proxy implementation itself.  
- Users are expected to provide their own proxy configurations if needed.  
