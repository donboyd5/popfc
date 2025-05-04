# first r section ----

libs <- function() {
  library(tidyverse)
  library(readxl)
  library(vroom)
  library(fs)
  library(skimr)
  library(Hmisc)
  library(btools)
}

suppressPackageStartupMessages(libs())

# ns(options())

DRAW <- here::here("data_raw")
DDATA <- here::here("data")

DNYSDOL <- here::here(DRAW, "nysdol")
DNYSDOH <- here::here(DRAW, "nysdoh")
DCENPOP <- here::here(DRAW, "census") # levels_components, totals


# new r section ----

print(DRAW)

x <- 10 # alt+-

# new section ctrl+k h ---------------------------------------------------
