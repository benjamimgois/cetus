# Graphical Interface - Application Visual Guide (v1.4)

## Window Layout

```
┌─────────────────────────────────────────────────────────┐
│                       Omnicom v1.0                    │
├─────────────────────────────────────────────────────────┤
│                                                         │
│                     Omnicom v1.0                      │
│                                                         │
│  ┌────────────────────────────────────────────────┐   │
│  │  Port Configuration                           │   │
│  ├────────────────────────────────────────────────┤   │
│  │                                                │   │
│  │  Port Type:    [USB (/dev/ttyUSB*)         ▼] │   │
│  │                                                │   │
│  │  Port:         [/dev/ttyUSB0               ▼] │   │
│  │                                                │   │
│  └────────────────────────────────────────────────┘   │
│                                                         │
│  ┌────────────────────────────────────────────────┐   │
│  │  Communication Parameters                     │   │
│  ├────────────────────────────────────────────────┤   │
│  │                                                │   │
│  │  Baud Rate:         [115200                ▼]  │   │
│  │                     └─────────────────────┘   │   │
│  │                      (highlighted in blue)    │   │
│  │                                                │   │
│  │  Data Bits:         [8                     ▼] │   │
│  │                                                │   │
│  │  Parity:            [None                  ▼] │   │
│  │                                                │   │
│  │  Stop Bits:         [1                     ▼] │   │
│  │                                                │   │
│  │  Flow Control:      [None                  ▼] │   │
│  │                                                │   │
│  └────────────────────────────────────────────────┘   │
│                                                         │
│            ┌───────────────────────────┐               │
│            │      CONNECT              │               │
│            └───────────────────────────┘               │
│               (large green button)                     │
│                                                         │
│              Ready to connect                          │
│              (status in green)                         │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## Visual Characteristics

### Colors and Styles

- **Background**: Light gray (#f5f5f5)
- **Groups**: White background with rounded borders
- **Baud Rate Field**: Blue highlight (#e3f2fd) with blue border (#2196f3)
- **Connect Button**: Green (#4caf50) with hover effect
- **Status**:
  - Green: Ready
  - Orange: Connecting
  - Blue: Waiting for password
  - Red: Error

### Interactions

1. **ComboBox Hover**: Border changes to blue
2. **Button Hover**: Darker green
3. **Button Click**: Even darker green
4. **Port Type Change**: Automatically updates list

### Dialogs

When you click CONNECT:

```
┌─────────────────────────────────────┐
│  ⓘ  Connection Started              │
├─────────────────────────────────────┤
│                                     │
│  Picocom terminal opened.           │
│                                     │
│  Port: /dev/ttyUSB0                 │
│  Baud Rate: 115200 baud             │
│  Configuration: 8N1                 │
│                                     │
│  Use Ctrl+A Ctrl+X to exit          │
│  picocom                            │
│                                     │
│           ┌────────┐                │
│           │   OK   │                │
│           └────────┘                │
└─────────────────────────────────────┘
```

### Responsiveness

- Fixed size: 550x500 pixels
- Consistent spacing: 15-20px
- Fields with adequate minimum height
- Labels aligned to the left
- Inputs occupy full available width

## Usage Flow

1. **Port Selection**
   - Choose between Serial or USB
   - List updates automatically
   - Port counter in status

2. **Configuration**
   - Baud rate is the main field (highlighted)
   - Safe default values (9600, 8N1)
   - All combos with common options

3. **Connection**
   - Click green button
   - Status changes to "Connecting..."
   - Terminal opens automatically
   - Informative dialog appears
   - Status indicates "enter password"

4. **picocom Terminal**
   - Opens in separate window
   - Requests sudo password
   - Starts serial communication
   - Ctrl+A Ctrl+X to exit

## Traceroute / MTR Tab (v1.4)

The Traceroute/MTR tab provides graphical real-time route visualization between the local machine and a target host.

### Layout

```
┌─────────────────────────────────────────────────────────┐
│  Traceroute / MTR                                       │
├──────────────────────────────┬──────────────────────────┤
│  Target: [_______________]   │  [TRACE]  [MTR]         │
├──────────────────────────────┴──────────────────────────┤
│                                                         │
│  Route Visualization (neon glowing bars)                │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Hop 1 ●━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  █  │  │
│  │  Hop 2 ●━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  █        │  │
│  │  Hop 3 ●━━━━━━━━━━━━━━━━━━━━━  █                │  │
│  │  ...                                             │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  Latency Graph (dark/neon aesthetic)                    │
│  ┌───────────────────────────────────────────────────┐  │
│  │  ms                                               │  │
│  │  100 ┤           ╭─╮                              │  │
│  │   50 ┤  ╭──╮  ╭──╯ ╰──╮                          │  │
│  │    0 ┼──╯  ╰──╯        ╰──────────────────────── │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### Route Visualization Features

- Each hop is represented as a **glowing neon bar** with hover effects
- Bar length represents relative latency (longer = higher latency)
- Hover over a hop to see details: IP, hostname, latency, packet loss
- Color intensity changes based on latency level

### MTR Mode

In MTR mode the route refreshes continuously, providing live statistics:

| Hop | IP Address    | Hostname         | Loss% | Avg ms |
|-----|---------------|------------------|-------|--------|
| 1   | 192.168.1.1   | router.local     | 0%    | 1.2    |
| 2   | 10.0.0.1      | isp-gateway      | 0%    | 8.4    |
| 3   | 203.0.113.5   | backbone-01      | 2%    | 22.1   |

### Permissions

The traceroute binary requires `cap_net_raw` for TCP/UDP probe types.
Omnicom automatically configures this when starting the traceroute tab:

```bash
# Applied automatically by Omnicom:
sudo setcap cap_net_raw+ep $(which traceroute)
```
