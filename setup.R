libs <- function() {
  library(tidyverse)
  tprint <- 75 # default tibble print
  options(tibble.print_max = tprint, tibble.print_min = tprint) # show up to tprint rows
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
DNYG <- here::here(DRAW, "data_ny_gov")
DNYSDOL <- here::here(DRAW, "nysdol")
DNYSDOH <- here::here(DRAW, "nysdoh")
DCENPOP <- here::here(DRAW, "census") # levels_components, totals
DCOC <- fs::path(DCENPOP, "components_of_change")
