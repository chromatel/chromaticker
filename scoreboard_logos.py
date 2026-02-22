#!/usr/bin/env python3
# Property of solutions reseaux chromatel
"""
NHL & NFL Team Logos - 32Ã¢â‚¬â€16 Pixel Art
Complete logos for all NHL and NFL teams.
'0' = transparent/black, '1' = primary color, '2' = secondary color
"""

# Simple circular logos for all teams (will be color-coded)
CIRCLE_LOGO = [
    "00000000011111111111100000000000",
    "00000001111111111111110000000000",
    "00000111111111111111111000000000",
    "00001111111111111111111100000000",
    "00011111111111111111111110000000",
    "00111111111111111111111111000000",
    "01111111111111111111111111100000",
    "01111111111111111111111111100000",
    "01111111111111111111111111100000",
    "01111111111111111111111111100000",
    "00111111111111111111111111000000",
    "00011111111111111111111110000000",
    "00001111111111111111111100000000",
    "00000111111111111111111000000000",
    "00000001111111111111110000000000",
    "00000000011111111111100000000000"
]

TEAM_LOGOS_32x16 = {
    # NHL Teams
    "BOS": {"colors": [(0,0,0), (252,181,20), (0,0,0)], "pixels": CIRCLE_LOGO},
    "BUF": {"colors": [(0,0,0), (0,32,91), (252,181,20)], "pixels": CIRCLE_LOGO},
    "DET": {"colors": [(0,0,0), (206,17,38), (255,255,255)], "pixels": CIRCLE_LOGO},
    "FLA": {"colors": [(0,0,0), (200,16,46), (4,30,66)], "pixels": CIRCLE_LOGO},
    "MTL": {"colors": [(0,0,0), (175,30,45), (0,48,135)], "pixels": CIRCLE_LOGO},
    "OTT": {"colors": [(0,0,0), (197,32,50), (198,146,20)], "pixels": CIRCLE_LOGO},
    "TBL": {"colors": [(0,0,0), (0,40,104), (255,255,255)], "pixels": CIRCLE_LOGO},
    "TOR": {"colors": [(0,0,0), (0,32,91), (255,255,255)], "pixels": CIRCLE_LOGO},
    "CAR": {"colors": [(0,0,0), (204,0,0), (0,0,0)], "pixels": CIRCLE_LOGO},
    "CBJ": {"colors": [(0,0,0), (0,38,84), (206,17,38)], "pixels": CIRCLE_LOGO},
    "NJD": {"colors": [(0,0,0), (206,17,38), (0,0,0)], "pixels": CIRCLE_LOGO},
    "NYI": {"colors": [(0,0,0), (0,83,155), (244,125,48)], "pixels": CIRCLE_LOGO},
    "NYR": {"colors": [(0,0,0), (0,51,160), (206,17,38)], "pixels": CIRCLE_LOGO},
    "PHI": {"colors": [(0,0,0), (247,73,2), (0,0,0)], "pixels": CIRCLE_LOGO},
    "PIT": {"colors": [(0,0,0), (252,181,20), (0,0,0)], "pixels": CIRCLE_LOGO},
    "WSH": {"colors": [(0,0,0), (200,16,46), (4,30,66)], "pixels": CIRCLE_LOGO},
    "ARI": {"colors": [(0,0,0), (140,38,51), (226,214,181)], "pixels": CIRCLE_LOGO},
    "CHI": {"colors": [(0,0,0), (207,10,44), (0,0,0)], "pixels": CIRCLE_LOGO},
    "COL": {"colors": [(0,0,0), (111,38,61), (35,97,146)], "pixels": CIRCLE_LOGO},
    "DAL": {"colors": [(0,0,0), (0,104,71), (142,144,144)], "pixels": CIRCLE_LOGO},
    "MIN": {"colors": [(0,0,0), (21,71,52), (165,25,46)], "pixels": CIRCLE_LOGO},
    "NSH": {"colors": [(0,0,0), (4,30,66), (255,184,28)], "pixels": CIRCLE_LOGO},
    "STL": {"colors": [(0,0,0), (0,47,135), (252,181,20)], "pixels": CIRCLE_LOGO},
    "WPG": {"colors": [(0,0,0), (4,30,66), (142,144,144)], "pixels": CIRCLE_LOGO},
    "ANA": {"colors": [(0,0,0), (252,76,2), (0,0,0)], "pixels": CIRCLE_LOGO},
    "CGY": {"colors": [(0,0,0), (200,16,46), (241,190,72)], "pixels": CIRCLE_LOGO},
    "EDM": {"colors": [(0,0,0), (252,76,2), (4,30,66)], "pixels": CIRCLE_LOGO},
    "LAK": {"colors": [(0,0,0), (162,170,173), (0,0,0)], "pixels": CIRCLE_LOGO},
    "SJS": {"colors": [(0,0,0), (0,109,117), (0,0,0)], "pixels": CIRCLE_LOGO},
    "SEA": {"colors": [(0,0,0), (0,22,40), (153,217,217)], "pixels": CIRCLE_LOGO},
    "VAN": {"colors": [(0,0,0), (0,32,91), (0,114,80)], "pixels": CIRCLE_LOGO},
    "VGK": {"colors": [(0,0,0), (51,63,72), (181,152,90)], "pixels": CIRCLE_LOGO},
    
    # NFL Teams
    "BUF-NFL": {"colors": [(0,0,0), (198,12,48), (0,51,141)], "pixels": CIRCLE_LOGO},
    "MIA": {"colors": [(0,0,0), (0,142,151), (252,76,2)], "pixels": CIRCLE_LOGO},
    "NE": {"colors": [(0,0,0), (0,34,68), (198,12,48)], "pixels": CIRCLE_LOGO},
    "NYJ": {"colors": [(0,0,0), (18,87,64), (255,255,255)], "pixels": CIRCLE_LOGO},
    "BAL": {"colors": [(0,0,0), (26,25,95), (0,0,0)], "pixels": CIRCLE_LOGO},
    "CIN": {"colors": [(0,0,0), (251,79,20), (0,0,0)], "pixels": CIRCLE_LOGO},
    "CLE": {"colors": [(0,0,0), (255,60,0), (49,29,0)], "pixels": CIRCLE_LOGO},
    "PIT-NFL": {"colors": [(0,0,0), (255,184,28), (0,0,0)], "pixels": CIRCLE_LOGO},
    "HOU": {"colors": [(0,0,0), (3,32,47), (167,25,48)], "pixels": CIRCLE_LOGO},
    "IND": {"colors": [(0,0,0), (0,44,95), (255,255,255)], "pixels": CIRCLE_LOGO},
    "JAX": {"colors": [(0,0,0), (0,103,120), (0,0,0)], "pixels": CIRCLE_LOGO},
    "TEN": {"colors": [(0,0,0), (12,35,64), (75,146,219)], "pixels": CIRCLE_LOGO},
    "DEN": {"colors": [(0,0,0), (251,79,20), (0,34,68)], "pixels": CIRCLE_LOGO},
    "KC": {"colors": [(0,0,0), (227,24,55), (255,184,28)], "pixels": CIRCLE_LOGO},
    "LV": {"colors": [(0,0,0), (165,172,175), (0,0,0)], "pixels": CIRCLE_LOGO},
    "LAC": {"colors": [(0,0,0), (0,128,198), (255,184,28)], "pixels": CIRCLE_LOGO},
    "DAL-NFL": {"colors": [(0,0,0), (0,34,68), (134,147,151)], "pixels": CIRCLE_LOGO},
    "NYG": {"colors": [(0,0,0), (1,35,82), (163,13,45)], "pixels": CIRCLE_LOGO},
    "PHI-NFL": {"colors": [(0,0,0), (0,76,84), (165,172,175)], "pixels": CIRCLE_LOGO},
    "WAS": {"colors": [(0,0,0), (90,20,20), (255,182,18)], "pixels": CIRCLE_LOGO},
    "CHI-NFL": {"colors": [(0,0,0), (11,22,42), (200,56,3)], "pixels": CIRCLE_LOGO},
    "DET-NFL": {"colors": [(0,0,0), (0,118,182), (176,183,188)], "pixels": CIRCLE_LOGO},
    "GB": {"colors": [(0,0,0), (24,48,40), (255,184,28)], "pixels": CIRCLE_LOGO},
    "MIN-NFL": {"colors": [(0,0,0), (79,38,131), (255,198,47)], "pixels": CIRCLE_LOGO},
    "ATL": {"colors": [(0,0,0), (167,25,48), (0,0,0)], "pixels": CIRCLE_LOGO},
    "CAR-NFL": {"colors": [(0,0,0), (0,133,202), (0,0,0)], "pixels": CIRCLE_LOGO},
    "NO": {"colors": [(0,0,0), (211,188,141), (0,0,0)], "pixels": CIRCLE_LOGO},
    "TB": {"colors": [(0,0,0), (213,10,10), (52,48,43)], "pixels": CIRCLE_LOGO},
    "ARI-NFL": {"colors": [(0,0,0), (151,35,63), (0,0,0)], "pixels": CIRCLE_LOGO},
    "LAR": {"colors": [(0,0,0), (0,53,148), (255,163,0)], "pixels": CIRCLE_LOGO},
    "SF": {"colors": [(0,0,0), (170,0,0), (173,153,93)], "pixels": CIRCLE_LOGO},
    "SEA-NFL": {"colors": [(0,0,0), (0,21,50), (105,190,40)], "pixels": CIRCLE_LOGO},
}

def render_logo_to_surface(team_code: str, width: int = 32, height: int = 16):
    """Render a team logo to a pygame Surface."""
    import pygame
    
    logo_data = TEAM_LOGOS_32x16.get(team_code.upper())
    if not logo_data:
        # Fallback: blank with team code
        surf = pygame.Surface((width, height))
        surf.fill((0, 0, 0))
        try:
            font = pygame.font.SysFont("monospace", 8, bold=True)
            text = font.render(team_code[:3].upper(), True, (255, 255, 255))
            x = (width - text.get_width()) // 2
            y = (height - text.get_height()) // 2
            surf.blit(text, (x, y))
        except:
            pass
        return surf
    
    colors = logo_data["colors"]
    pixels = logo_data["pixels"]
    
    surf = pygame.Surface((width, height))
    surf.fill((0, 0, 0))
    
    for y, row in enumerate(pixels):
        for x, pixel in enumerate(row):
            if pixel != '0':
                # pixel '1' should use colors[1] (primary), '2' uses colors[2] (secondary)
                # colors[0] is background black, so we use the pixel value directly as index
                color_idx = int(pixel)
                if 0 <= color_idx < len(colors):
                    color = colors[color_idx]
                    # Only render if not black (don't render black on black)
                    if color != (0, 0, 0):
                        surf.set_at((x, y), color)
    
    return surf

# NFL team code mappings
NFL_TEAM_CODE_MAP = {
    "NE": "NE", "BUF": "BUF-NFL", "MIA": "MIA", "NYJ": "NYJ",
    "BAL": "BAL", "CIN": "CIN", "CLE": "CLE", "PIT": "PIT-NFL",
    "HOU": "HOU", "IND": "IND", "JAX": "JAX", "TEN": "TEN",
    "DEN": "DEN", "KC": "KC", "LV": "LV", "LAC": "LAC",
    "DAL": "DAL-NFL", "NYG": "NYG", "PHI": "PHI-NFL", "WAS": "WAS",
    "CHI": "CHI-NFL", "DET": "DET-NFL", "GB": "GB", "MIN": "MIN-NFL",
    "ATL": "ATL", "CAR": "CAR-NFL", "NO": "NO", "TB": "TB",
    "ARI": "ARI-NFL", "LAR": "LAR", "SF": "SF", "SEA": "SEA-NFL",
}

def get_nfl_logo_code(espn_code: str) -> str:
    """Map ESPN team code to logo code."""
    return NFL_TEAM_CODE_MAP.get(espn_code.upper(), espn_code.upper())
