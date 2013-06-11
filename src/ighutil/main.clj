(ns ighutil.main
  (:require [cliopatra.command :as command :refer [defcommand]])
  (:gen-class
   :name ighutil.main))

(defn -main [& args]
  (command/dispatch
   ['ighutil.mutation-by-read
    'ighutil.mutationwalker]
   args))
