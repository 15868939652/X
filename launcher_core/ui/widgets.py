"""Reusable widget factory functions extracted from app.py."""

import customtkinter as ctk
import tkinter as tk


def panel(parent, fg="#FFFFFF", border="#D8E3EE", radius=16):
    return ctk.CTkFrame(parent, fg_color=fg, corner_radius=radius, border_width=1, border_color=border)


def title(parent, text: str, size: int = 13):
    return ctk.CTkLabel(
        parent,
        text=text,
        font=ctk.CTkFont(family="Microsoft YaHei UI", size=size, weight="bold"),
        text_color="#133248",
    )


def subtext(parent, text: str, wrap: int = 270):
    return ctk.CTkLabel(
        parent,
        text=text,
        justify="left",
        wraplength=wrap,
        font=ctk.CTkFont(family="Microsoft YaHei UI", size=11),
        text_color="#6B8195",
    )


def entry_row(parent, label: str, variable: tk.StringVar):
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", pady=(12, 0))
    ctk.CTkLabel(row, text=label, font=ctk.CTkFont(family="Microsoft YaHei UI", size=12, weight="bold"), text_color="#617A91").pack(side="left")
    entry = ctk.CTkEntry(row, width=96, height=36, textvariable=variable, justify="center", corner_radius=12)
    entry.pack(side="right")
    return entry


def bind_click(widget, callback) -> None:
    widget.bind("<Button-1>", callback)
    for child in widget.winfo_children():
        bind_click(child, callback)
