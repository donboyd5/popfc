libs <- function() {
  library(tidyverse)
  library(readxl)
  library(vroom)
  library(fs)
  library(skimr)
  library(Hmisc)
  library(gt)
  library(btools)
}

suppressPackageStartupMessages(libs())

# ns(options())

DRAW <- here::here("data_raw")
DDATA <- here::here("data")
DWORK <- here::here("data_work")

DCDC <- here::here(DRAW, "cdc")
DNYSDOL <- here::here(DRAW, "nysdol")
DNYSDOH <- here::here(DRAW, "nysdoh")
DCENPOP <- here::here(DRAW, "census") # levels_components, totals
